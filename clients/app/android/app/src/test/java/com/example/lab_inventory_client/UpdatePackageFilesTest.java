package com.example.lab_inventory_client;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;

/** Standalone JVM regression test; run with the build JDK, no Android mock. */
public final class UpdatePackageFilesTest {
    private static int passed;
    private static void check(boolean condition) {
        if (!condition) throw new AssertionError();
        passed++;
    }
    private static void rejects(File cache, String path, long size, String hash, String code) throws Exception {
        try { UpdatePackageFiles.verify(cache, path, size, hash); throw new AssertionError("accepted invalid package"); }
        catch (UpdatePackageFiles.VerificationException error) { check(code.equals(error.code)); }
    }
    public static void main(String[] args) throws Exception {
        Path work = Path.of(args[0]).toRealPath();
        Path cache = Files.createDirectory(work.resolve("cache"));
        Path updates = Files.createDirectory(cache.resolve("client-updates"));
        Path scope = Files.createDirectory(updates.resolve("scope"));
        Path file = Files.write(scope.resolve("update.apk"), new byte[]{1,2,3});
        StringBuilder hash = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(new byte[]{1,2,3})) hash.append(String.format("%02x", value & 255));
        String expected = hash.toString();
        check(UpdatePackageFiles.verify(cache.toFile(),file.toString(),3,expected).equals(file.toFile()));
        Path alias = Files.createSymbolicLink(work.resolve("cache-alias"),cache);
        Path aliased = alias.resolve("client-updates/scope/update.apk");
        check(!aliased.toFile().getAbsolutePath().equals(aliased.toFile().getCanonicalPath())); // old rejection
        check(UpdatePackageFiles.verify(cache.toFile(),aliased.toString(),3,expected).equals(file.toFile()));
        Path outside = Files.write(work.resolve("outside.apk"),new byte[]{1,2,3});
        rejects(cache.toFile(),outside.toString(),3,expected,"INSTALL_CACHE_PATH");
        Path escape = Files.createSymbolicLink(scope.resolve("escape.apk"),outside);
        rejects(cache.toFile(),escape.toString(),3,expected,"INSTALL_CACHE_PATH");
        Path sibling = Files.createDirectory(cache.resolve("client-updates-evil"));
        rejects(cache.toFile(),Files.write(sibling.resolve("update.apk"),new byte[]{1,2,3}).toString(),3,expected,"INSTALL_CACHE_PATH");
        rejects(cache.toFile(),file.toString(),2,expected,"INSTALL_PACKAGE_SIZE");
        rejects(cache.toFile(),file.toString(),3,"0".repeat(64),"INSTALL_PACKAGE_HASH");
        rejects(cache.toFile(),scope.resolve("missing.apk").toString(),3,expected,"INSTALL_PACKAGE_SIZE");
        System.out.println("JVM update-cache checks passed: "+passed);
    }
}
