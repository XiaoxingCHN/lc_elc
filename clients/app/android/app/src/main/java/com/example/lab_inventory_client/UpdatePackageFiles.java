package com.example.lab_inventory_client;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** Resolve aliases before enforcing the private update-cache boundary. */
public final class UpdatePackageFiles {
    private UpdatePackageFiles() {}

    public static final class VerificationException extends IOException {
        public final String code;
        public VerificationException(String code, String message) {
            super(message);
            this.code = code;
        }
    }

    public static File verify(File cacheDir, String path, long size, String hash)
            throws IOException, NoSuchAlgorithmException {
        File root = new File(cacheDir, "client-updates").getCanonicalFile();
        File file = new File(path).getCanonicalFile();
        // /data/user/0 and vendor aliases can name the same private cache.
        // Canonical containment still rejects links that escape the cache.
        if (!file.getPath().startsWith(root.getPath() + File.separator)) {
            throw new VerificationException("INSTALL_CACHE_PATH", "更新文件不在应用私有缓存目录内，请重新下载。");
        }
        if (!file.isFile() || size <= 0 || size > 536870912L || file.length() != size) {
            throw new VerificationException("INSTALL_PACKAGE_SIZE", "更新包不完整或已被清理，请重新下载。");
        }
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[65536];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        StringBuilder actual = new StringBuilder();
        for (byte value : digest.digest()) actual.append(String.format("%02x", value & 255));
        if (!actual.toString().equals(hash)) {
            throw new VerificationException("INSTALL_PACKAGE_HASH", "更新包校验不一致，请重新下载。");
        }
        return file;
    }
}
