import com.android.tools.smali.dexlib2.Opcode;
import com.android.tools.smali.dexlib2.builder.MutableMethodImplementation;
import com.android.tools.smali.dexlib2.builder.instruction.BuilderInstruction21c;
import com.android.tools.smali.dexlib2.builder.instruction.BuilderInstruction35c;
import com.android.tools.smali.dexlib2.dexbacked.DexBackedDexFile;
import com.android.tools.smali.dexlib2.iface.Method;
import com.android.tools.smali.dexlib2.iface.instruction.FiveRegisterInstruction;
import com.android.tools.smali.dexlib2.iface.instruction.Instruction;
import com.android.tools.smali.dexlib2.iface.instruction.OneRegisterInstruction;
import com.android.tools.smali.dexlib2.iface.instruction.ReferenceInstruction;
import com.android.tools.smali.dexlib2.immutable.ImmutableMethod;
import com.android.tools.smali.dexlib2.immutable.reference.ImmutableMethodReference;
import com.android.tools.smali.dexlib2.immutable.reference.ImmutableStringReference;
import com.android.tools.smali.dexlib2.rewriter.DexRewriter;
import com.android.tools.smali.dexlib2.rewriter.Rewriter;
import com.android.tools.smali.dexlib2.rewriter.RewriterModule;
import com.android.tools.smali.dexlib2.rewriter.Rewriters;
import com.android.tools.smali.dexlib2.writer.io.MemoryDataStore;
import com.android.tools.smali.dexlib2.writer.pool.DexPool;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;

public class PatchGadget {
    private static final String TARGET = "Lcom/ace/gshell/AceApplication;";
    private static final ImmutableMethodReference LOAD_LIBRARY = new ImmutableMethodReference(
        "Ljava/lang/System;", "loadLibrary", List.of("Ljava/lang/String;"), "V");

    private static Method initializer(DexBackedDexFile dex) {
        Method found = null;
        for (var definition : dex.getClasses()) {
            if (!definition.getType().equals(TARGET)) continue;
            for (var method : definition.getDirectMethods()) {
                if (!method.getName().equals("<clinit>")) continue;
                if (found != null) throw new IllegalStateException("Ambiguous ACE initializer");
                found = method;
            }
        }
        if (found == null) throw new IllegalStateException("ACE initializer missing");
        return found;
    }

    private static List<String> describe(Method method) {
        var result = new ArrayList<String>();
        for (Instruction instruction : method.getImplementation().getInstructions()) {
            String item = instruction.getOpcode().name();
            if (instruction instanceof OneRegisterInstruction one) item += ":" + one.getRegisterA();
            if (instruction instanceof FiveRegisterInstruction five) {
                item += ":" + five.getRegisterCount() + ":" + five.getRegisterC() + ":" + five.getRegisterD()
                    + ":" + five.getRegisterE() + ":" + five.getRegisterF() + ":" + five.getRegisterG();
            }
            if (instruction instanceof ReferenceInstruction reference) item += ":" + reference.getReference();
            result.add(item);
        }
        return result;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Source DEX and new output path required");
        Path source = Path.of(args[0]);
        Path target = Path.of(args[1]);
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalArgumentException("Output must be a new file");
        }
        var original = new DexBackedDexFile(null, Files.readAllBytes(source));
        Method before = initializer(original);
        var implementation = before.getImplementation();
        if (!before.getParameterTypes().isEmpty() || !before.getReturnType().equals("V") || implementation == null
            || implementation.getRegisterCount() != 1 || !implementation.getTryBlocks().isEmpty()) {
            throw new IllegalStateException("Unsupported ACE initializer layout");
        }
        var instructions = new ArrayList<Instruction>();
        implementation.getInstructions().forEach(instructions::add);
        var expectedOpcodes = List.of(Opcode.CONST_STRING, Opcode.INVOKE_STATIC, Opcode.CONST_STRING,
            Opcode.INVOKE_STATIC, Opcode.NEW_INSTANCE, Opcode.INVOKE_DIRECT, Opcode.SPUT_OBJECT, Opcode.RETURN_VOID);
        if (!instructions.stream().map(Instruction::getOpcode).toList().equals(expectedOpcodes)) {
            throw new IllegalStateException("Unsupported or already patched ACE initializer");
        }
        var originalDescription = describe(before);
        if (!originalDescription.get(0).equals("CONST_STRING:0:tprt")
            || !originalDescription.get(1).equals("INVOKE_STATIC:1:0:0:0:0:0:" + LOAD_LIBRARY)
            || !originalDescription.get(2).equals("CONST_STRING:0:tersafe2")
            || !originalDescription.get(3).equals(originalDescription.get(1))) {
            throw new IllegalStateException("Unexpected ACE native load sequence");
        }
        var mutable = new MutableMethodImplementation(implementation);
        mutable.addInstruction(0, new BuilderInstruction21c(Opcode.CONST_STRING, 0, new ImmutableStringReference("gadget")));
        mutable.addInstruction(1, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 1, 0, 0, 0, 0, 0, LOAD_LIBRARY));
        var replacement = new ImmutableMethod(before.getDefiningClass(), before.getName(), before.getParameters(),
            before.getReturnType(), before.getAccessFlags(), before.getAnnotations(), before.getHiddenApiRestrictions(), mutable);
        var rewriter = new DexRewriter(new RewriterModule() {
            @Override
            public Rewriter<Method> getMethodRewriter(Rewriters rewriters) {
                return method -> method.getDefiningClass().equals(TARGET) && method.getName().equals("<clinit>")
                    ? replacement : method;
            }
        });
        var store = new MemoryDataStore();
        DexPool.writeTo(store, rewriter.getDexFileRewriter().rewrite(original));
        byte[] result = store.getData();
        var verified = new DexBackedDexFile(null, result);
        var after = describe(initializer(verified));
        if (verified.getClasses().size() != original.getClasses().size()
            || after.size() != originalDescription.size() + 2
            || !after.get(0).equals("CONST_STRING:0:gadget")
            || !after.get(1).equals(originalDescription.get(1))
            || !after.subList(2, after.size()).equals(originalDescription)) {
            throw new IllegalStateException("Gadget DEX verification failed");
        }
        Files.write(target, result, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        System.out.printf("{\"class_count\":%d,\"original_instructions\":%d,\"patched_instructions\":%d,\"original_tail_preserved\":true}%n",
            verified.getClasses().size(), originalDescription.size(), after.size());
    }
}
