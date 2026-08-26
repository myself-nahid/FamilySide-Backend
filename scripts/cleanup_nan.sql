-- Cleanup NaN values in platform_items
-- Review and run on staging before production. Backup recommended.

-- 1) Convert text 'nan' (case-insensitive) in text columns to NULL
UPDATE platform_items
SET description = NULL
WHERE description IS NOT NULL AND lower(trim(description)) = 'nan';

-- You can add other text columns here if needed, for example:
-- UPDATE platform_items SET website = NULL WHERE website IS NOT NULL AND trim(website) = '';

-- 2) Replace numeric NaN in numeric columns with a safe default (price -> 0)
UPDATE platform_items
SET price = 0
WHERE price IS NOT NULL AND price = 'NaN'::float8;

-- 3) Optional: normalize empty strings to NULL for contact fields
-- UPDATE platform_items SET website = NULL WHERE website IS NOT NULL AND trim(website) = '';
-- UPDATE platform_items SET email = NULL WHERE email IS NOT NULL AND trim(email) = '';

-- End of cleanup
