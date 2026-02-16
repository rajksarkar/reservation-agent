import { describe, it, expect } from "vitest";
import { encrypt, decrypt } from "../crypto";

// Must set ENCRYPTION_KEY before importing crypto functions
process.env.ENCRYPTION_KEY = "test-master-key-for-vitest";

const USER_ID = "550e8400-e29b-41d4-a716-446655440000";

describe("crypto", () => {
  describe("encrypt / decrypt roundtrip", () => {
    it("roundtrips a simple string", () => {
      const { encrypted, iv, tag } = encrypt("hello-world", USER_ID);
      const result = decrypt(encrypted, iv, tag, USER_ID);
      expect(result).toBe("hello-world");
    });

    it("roundtrips special characters", () => {
      const values = ["p@$$w0rd!#%", "café", "日本語テスト", "emoji 🎉"];
      for (const val of values) {
        const { encrypted, iv, tag } = encrypt(val, USER_ID);
        expect(decrypt(encrypted, iv, tag, USER_ID)).toBe(val);
      }
    });

    it("roundtrips an empty string", () => {
      const { encrypted, iv, tag } = encrypt("", USER_ID);
      expect(decrypt(encrypted, iv, tag, USER_ID)).toBe("");
    });

    it("produces different ciphertexts for the same plaintext (random IV)", () => {
      const a = encrypt("same-value", USER_ID);
      const b = encrypt("same-value", USER_ID);
      expect(a.encrypted).not.toBe(b.encrypted);
      expect(a.iv).not.toBe(b.iv);
    });
  });

  describe("deriveKey determinism", () => {
    it("produces the same key for the same userId", () => {
      // Encrypt with same userId twice; both should decrypt with same key
      const { encrypted, iv, tag } = encrypt("test", USER_ID);
      const result = decrypt(encrypted, iv, tag, USER_ID);
      expect(result).toBe("test");
    });

    it("different userIds cannot decrypt each other", () => {
      const { encrypted, iv, tag } = encrypt("secret", "user-a");
      expect(() => decrypt(encrypted, iv, tag, "user-b")).toThrow();
    });
  });

  describe("cross-language compatibility", () => {
    it("IV and tag are base64 encoded", () => {
      const { iv, tag } = encrypt("test", USER_ID);
      // Valid base64 should decode without error
      expect(() => Buffer.from(iv, "base64")).not.toThrow();
      expect(() => Buffer.from(tag, "base64")).not.toThrow();
      // IV should be 16 bytes, tag should be 16 bytes
      expect(Buffer.from(iv, "base64").length).toBe(16);
      expect(Buffer.from(tag, "base64").length).toBe(16);
    });

    it("encrypted output is base64 encoded", () => {
      const { encrypted } = encrypt("test-value", USER_ID);
      expect(() => Buffer.from(encrypted, "base64")).not.toThrow();
    });
  });
});
