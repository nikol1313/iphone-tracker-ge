-- Sample data for the Postman API tests in CI, where the database starts empty.
-- One phone sold by two stores, with a short price history.
-- Lowest price ever is 1999.00, so tests 23 and 25 must agree on it.

WITH store_a AS (
    INSERT INTO stores (title, web_url) VALUES ('Test Store A', 'https://store-a.example.com') RETURNING id
), store_b AS (
    INSERT INTO stores (title, web_url) VALUES ('Test Store B', 'https://store-b.example.com') RETURNING id
), phone AS (
    INSERT INTO products (brand, model, storage, color, identity_key, is_active)
    VALUES ('Apple', 'iPhone 15', '128GB', 'Black',
            'apple' || chr(31) || 'iphone 15' || chr(31) || '128gb' || chr(31) || 'black', true)
    RETURNING id
), listings AS (
    INSERT INTO product_listing
        (store_id, product_id, product_url, current_price, currency, last_checked_at, is_active, is_available)
    SELECT store_a.id, phone.id, 'https://store-a.example.com/iphone-15', 1999.00, 'GEL', now(), true, true
    FROM store_a, phone
    UNION ALL
    SELECT store_b.id, phone.id, 'https://store-b.example.com/iphone-15', 2149.00, 'GEL', now(), true, true
    FROM store_b, phone
    RETURNING id, current_price
)
INSERT INTO price_history (listing_id, price, currency, is_available, recorded_at)
SELECT id, current_price + 100, 'GEL', true, now() - interval '2 days' FROM listings
UNION ALL
SELECT id, current_price, 'GEL', true, now() - interval '1 day' FROM listings;
