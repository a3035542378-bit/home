import com.android.tools.smali.dexlib2.Opcode;
import com.android.tools.smali.dexlib2.dexbacked.DexBackedDexFile;
import com.android.tools.smali.dexlib2.iface.Method;
import com.android.tools.smali.dexlib2.iface.instruction.Instruction;
import com.android.tools.smali.dexlib2.iface.instruction.ReferenceInstruction;
import com.android.tools.smali.dexlib2.iface.reference.MethodReference;
import com.android.tools.smali.dexlib2.immutable.ImmutableMethod;
import com.android.tools.smali.dexlib2.immutable.ImmutableMethodImplementation;
import com.android.tools.smali.dexlib2.immutable.instruction.ImmutableInstruction10x;
import com.android.tools.smali.dexlib2.rewriter.DexRewriter;
import com.android.tools.smali.dexlib2.rewriter.Rewriter;
import com.android.tools.smali.dexlib2.rewriter.RewriterModule;
import com.android.tools.smali.dexlib2.rewriter.Rewriters;
import com.android.tools.smali.dexlib2.writer.pool.DexPool;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collections;

public class PatchAce {
    public static void main(String[] args) throws Exception {
        if (args.length != 2 || Files.exists(Path.of(args[1]))) {
            throw new IllegalArgumentException("Source DEX and new output path required");
        }
        var original = new DexBackedDexFile(null, Files.readAllBytes(Path.of(args[0])));
        int[] changed = {0};
        var rewriter = new DexRewriter(new RewriterModule() {
            @Override
            public Rewriter<Method> getMethodRewriter(Rewriters rewriters) {
                return method -> {
                    if (!method.getDefiningClass().equals("Lcom/ace/gshell/AceApplication;") || !method.getName().equals("attachBaseContext")) return method;
                    if (!method.getParameterTypes().equals(Collections.singletonList("Landroid/content/Context;")) || !method.getReturnType().equals("V")) {
                        throw new IllegalStateException("Unexpected attachBaseContext signature");
                    }
                    var implementation = method.getImplementation();
                    Instruction parentCall = null;
                    for (Instruction instruction : implementation.getInstructions()) {
                        if (instruction.getOpcode() != Opcode.INVOKE_SUPER && instruction.getOpcode() != Opcode.INVOKE_SUPER_RANGE) continue;
                        var reference = (MethodReference) ((ReferenceInstruction) instruction).getReference();
                        if (reference.getName().equals("attachBaseContext") && reference.getDefiningClass().equals("Landroid/app/Application;")) parentCall = instruction;
                    }
                    if (parentCall == null) throw new IllegalStateException("Parent context initialization not found");
                    changed[0]++;
                    var replacement = new ImmutableMethodImplementation(implementation.getRegisterCount(),
                        Arrays.asList(parentCall, new ImmutableInstruction10x(Opcode.RETURN_VOID)), Collections.emptyList(), Collections.emptyList());
                    return new ImmutableMethod(method.getDefiningClass(), method.getName(), method.getParameters(), method.getReturnType(),
                        method.getAccessFlags(), method.getAnnotations(), method.getHiddenApiRestrictions(), replacement);
                };
            }
        });
        DexPool.writeTo(args[1], rewriter.getDexFileRewriter().rewrite(original));
        if (changed[0] != 1) {
            Files.delete(Path.of(args[1]));
            throw new IllegalStateException("Expected exactly one ACE context initialization method");
        }
        var output = new DexBackedDexFile(null, Files.readAllBytes(Path.of(args[1])));
        if (output.getClasses().size() != original.getClasses().size()) throw new IllegalStateException("DEX class count changed");
        System.out.printf("{\"patched_methods\":1,\"class_count\":%d}%n", output.getClasses().size());
    }
}
