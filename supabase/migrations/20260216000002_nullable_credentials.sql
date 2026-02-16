-- Allow platform_accounts to be created without encrypted credentials
-- (browser-based auth stores session_data instead)
ALTER TABLE public.platform_accounts
  ALTER COLUMN encrypted_username DROP NOT NULL,
  ALTER COLUMN encrypted_password DROP NOT NULL,
  ALTER COLUMN encryption_iv DROP NOT NULL,
  ALTER COLUMN encryption_tag DROP NOT NULL;
