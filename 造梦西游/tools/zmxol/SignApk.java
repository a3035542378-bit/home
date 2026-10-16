import com.android.apksig.ApkSigner;
import com.android.apksig.ApkVerifier;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.Collections;

public class SignApk {
    public static void main(String[] args) throws Exception {
        if (args.length != 4) throw new IllegalArgumentException("input output private-key-der certificate-der required");
        File output = new File(args[1]);
        if (output.exists()) throw new IllegalArgumentException("Output must be a new file");
        PrivateKey key = KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))));
        X509Certificate certificate;
        try (var input = Files.newInputStream(Path.of(args[3]))) {
            certificate = (X509Certificate) CertificateFactory.getInstance("X.509").generateCertificate(input);
        }
        var config = new ApkSigner.SignerConfig.Builder("offline-test", key, Collections.singletonList(certificate)).build();
        new ApkSigner.Builder(Collections.singletonList(config))
            .setInputApk(new File(args[0])).setOutputApk(output).setMinSdkVersion(10)
            .setV1SigningEnabled(true).setV2SigningEnabled(true).setV3SigningEnabled(true)
            .setV4SigningEnabled(false).setOtherSignersSignaturesPreserved(false).build().sign();
        var result = new ApkVerifier.Builder(output).setMinCheckedPlatformVersion(10).build().verify();
        if (!result.isVerified()) throw new IllegalStateException("APK signature verification failed: " + result.getErrors());
        System.out.printf("{\"verified\":true,\"v1\":%s,\"v2\":%s,\"v3\":%s}%n",
            result.isVerifiedUsingV1Scheme(), result.isVerifiedUsingV2Scheme(), result.isVerifiedUsingV3Scheme());
    }
}
