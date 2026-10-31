CREATE TABLE IF NOT EXISTS categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  display_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Canonical article topics. Country names belong in destinations, not categories.
INSERT INTO categories (name, slug, description, display_order) VALUES
  ('Cẩm nang', 'cam-nang', 'Hướng dẫn dễ áp dụng để chuẩn bị và tận hưởng chuyến đi.', 1),
  ('Kinh nghiệm du lịch', 'kinh-nghiem-du-lich', 'Kinh nghiệm thực tế, mẹo hữu ích và lưu ý trước chuyến đi.', 2),
  ('Điểm đến', 'diem-den', 'Giới thiệu quốc gia, thành phố và những nơi đáng khám phá.', 3),
  ('Check-in', 'check-in', 'Góc chụp đẹp, địa điểm nổi bật và trải nghiệm đáng lưu lại.', 4),
  ('Ẩm thực', 'am-thuc', 'Món ngon địa phương, hàng quán và văn hóa ẩm thực.', 5),
  ('Hotel review', 'hotel-review', 'Đánh giá khách sạn, resort, homestay và nơi lưu trú.', 6),
  ('Lịch trình', 'lich-trinh', 'Lịch trình tham khảo theo số ngày, khu vực và ngân sách.', 7),
  ('Di chuyển', 'di-chuyen', 'Cách đi lại, phương tiện và mẹo di chuyển tại điểm đến.', 8),
  ('Văn hóa & địa phương', 'van-hoa-dia-phuong', 'Văn hóa, phong tục và những câu chuyện từ cộng đồng bản địa.', 9),
  ('Chi phí & ngân sách', 'chi-phi-du-lich', 'Dự trù chi phí và lên ngân sách cho chuyến đi.', 10),
  ('Tin du lịch', 'tin-du-lich', 'Tin mới, thay đổi và thông tin đáng chú ý trong ngành du lịch.', 11)
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, display_order = EXCLUDED.display_order;

-- Geographic taxonomy: countries are root records, and cities are children of countries.
CREATE TABLE IF NOT EXISTS destinations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('country', 'city')),
  parent_id UUID REFERENCES destinations(id) ON DELETE CASCADE,
  description TEXT NOT NULL DEFAULT '',
  cover_image TEXT NOT NULL DEFAULT '',
  display_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT destinations_parent_kind_check CHECK (
    (kind = 'country' AND parent_id IS NULL) OR
    (kind = 'city' AND parent_id IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS destinations_parent_idx ON destinations (parent_id, display_order, name);
CREATE INDEX IF NOT EXISTS destinations_kind_idx ON destinations (kind, display_order, name);

-- Starter country directory: each country can later hold cities and all editorial topics.
INSERT INTO destinations (name, slug, kind, parent_id, description, display_order, updated_at) VALUES
  ('Việt Nam', 'viet-nam', 'country', NULL, 'Từ những thành phố sôi động đến biển đảo, núi rừng và di sản bản địa.', 1, NOW()),
  ('Nhật Bản', 'nhat-ban', 'country', NULL, 'Khám phá văn hóa, ẩm thực, thành phố và những mùa du lịch tại Nhật Bản.', 2, NOW()),
  ('Thái Lan', 'thai-lan', 'country', NULL, 'Cẩm nang thành phố, bãi biển, ẩm thực đường phố và trải nghiệm ở Thái Lan.', 3, NOW()),
  ('Hàn Quốc', 'han-quoc', 'country', NULL, 'Kinh nghiệm, ẩm thực, mua sắm và các điểm đến tại Hàn Quốc.', 4, NOW()),
  ('Singapore', 'singapore', 'country', NULL, 'Gợi ý khám phá thành phố, ẩm thực và trải nghiệm tại Singapore.', 5, NOW()),
  ('Malaysia', 'malaysia', 'country', NULL, 'Thành phố đa văn hóa, thiên nhiên và món ngon ở Malaysia.', 6, NOW()),
  ('Indonesia', 'indonesia', 'country', NULL, 'Đảo, văn hóa, lưu trú và kinh nghiệm khám phá Indonesia.', 7, NOW()),
  ('Đài Loan', 'dai-loan', 'country', NULL, 'Chợ đêm, tuyến tàu, thiên nhiên và trải nghiệm tại Đài Loan.', 8, NOW()),
  ('Trung Quốc', 'trung-quoc', 'country', NULL, 'Thành phố, di sản, ẩm thực và cẩm nang du lịch Trung Quốc.', 9, NOW()),
  ('Lào', 'lao', 'country', NULL, 'Những hành trình chậm, văn hóa và thiên nhiên tại Lào.', 10, NOW()),
  ('Campuchia', 'campuchia', 'country', NULL, 'Di sản, ẩm thực và những điểm đến nổi bật ở Campuchia.', 11, NOW()),
  ('Pháp', 'phap', 'country', NULL, 'Thành phố, ẩm thực, nghệ thuật và kinh nghiệm du lịch Pháp.', 12, NOW()),
  ('Ý', 'y', 'country', NULL, 'Các thành phố lịch sử, ẩm thực và hành trình tại Ý.', 13, NOW()),
  ('Úc', 'uc', 'country', NULL, 'Thiên nhiên, thành phố và cẩm nang khám phá nước Úc.', 14, NOW()),
  ('Hoa Kỳ', 'hoa-ky', 'country', NULL, 'Gợi ý hành trình, thành phố và trải nghiệm tại Hoa Kỳ.', 15, NOW())
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, kind = 'country', parent_id = NULL,
  description = CASE WHEN destinations.description = '' THEN EXCLUDED.description ELSE destinations.description END,
  display_order = EXCLUDED.display_order, updated_at = NOW();

-- Back-office accounts and role-based permissions. The root admin from .env is kept separate.
CREATE TABLE IF NOT EXISTS admin_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'author' CHECK (role IN ('admin', 'editor', 'author', 'viewer')),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS admin_users_role_active_idx ON admin_users (role, active);

CREATE TABLE IF NOT EXISTS posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  excerpt TEXT NOT NULL DEFAULT '',
  content_html TEXT NOT NULL DEFAULT '',
  cover_image TEXT NOT NULL DEFAULT '',
  cover_alt TEXT NOT NULL DEFAULT '',
  cover_credit TEXT NOT NULL DEFAULT '',
  category_name TEXT NOT NULL DEFAULT 'Cẩm nang',
  category_slug TEXT NOT NULL DEFAULT 'cam-nang',
  country_id UUID REFERENCES destinations(id) ON DELETE SET NULL,
  country_name TEXT NOT NULL DEFAULT '',
  country_slug TEXT NOT NULL DEFAULT '',
  destination_id UUID REFERENCES destinations(id) ON DELETE SET NULL,
  destination_name TEXT NOT NULL DEFAULT '',
  destination_slug TEXT NOT NULL DEFAULT '',
  tags TEXT[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
  featured BOOLEAN NOT NULL DEFAULT FALSE,
  featured_until TIMESTAMPTZ,
  author_name TEXT NOT NULL DEFAULT 'Ban biên tập',
  created_by UUID REFERENCES admin_users(id) ON DELETE SET NULL,
  updated_by UUID REFERENCES admin_users(id) ON DELETE SET NULL,
  source_url TEXT,
  source_name TEXT NOT NULL DEFAULT '',
  seo_title TEXT NOT NULL DEFAULT '',
  seo_description TEXT NOT NULL DEFAULT '',
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Safe, additive migrations for installations that were initialized with the earlier schema.
ALTER TABLE posts ADD COLUMN IF NOT EXISTS featured_until TIMESTAMPTZ;
UPDATE posts SET featured_until = NOW() + INTERVAL '7 days' WHERE featured = TRUE AND featured_until IS NULL;
CREATE INDEX IF NOT EXISTS posts_featured_until_idx ON posts (featured, featured_until DESC);
ALTER TABLE posts ADD COLUMN IF NOT EXISTS cover_credit TEXT NOT NULL DEFAULT '';
ALTER TABLE posts ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES admin_users(id) ON DELETE SET NULL;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS updated_by UUID REFERENCES admin_users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS posts_created_by_idx ON posts (created_by, updated_at DESC);
ALTER TABLE posts ADD COLUMN IF NOT EXISTS country_id UUID REFERENCES destinations(id) ON DELETE SET NULL;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS country_name TEXT NOT NULL DEFAULT '';
ALTER TABLE posts ADD COLUMN IF NOT EXISTS country_slug TEXT NOT NULL DEFAULT '';
ALTER TABLE posts ADD COLUMN IF NOT EXISTS destination_id UUID REFERENCES destinations(id) ON DELETE SET NULL;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS destination_name TEXT NOT NULL DEFAULT '';
ALTER TABLE posts ADD COLUMN IF NOT EXISTS destination_slug TEXT NOT NULL DEFAULT '';

-- Normalize legacy geography-as-topic labels into the editorial category system.
UPDATE posts SET category_name = 'Điểm đến', category_slug = 'diem-den', updated_at = NOW()
  WHERE category_slug IN ('the-gioi', 'diem-den-viet-nam', 'destinations', 'destination');
UPDATE posts SET category_name = 'Hotel review', category_slug = 'hotel-review', updated_at = NOW()
  WHERE category_slug IN ('hotel', 'hotels', 'hotel-reviews', 'review-khach-san', 'khach-san', 'homestay', 'resort-review');
UPDATE posts SET category_name = 'Ẩm thực', category_slug = 'am-thuc', updated_at = NOW()
  WHERE category_slug IN ('food', 'food-guide', 'street-food', 'food-and-drink', 'cuisine');
UPDATE posts SET category_name = 'Cẩm nang', category_slug = 'cam-nang', updated_at = NOW()
  WHERE category_slug IN ('guide', 'guides', 'travel-guide', 'travel-guides');
UPDATE posts SET category_name = 'Kinh nghiệm du lịch', category_slug = 'kinh-nghiem-du-lich', updated_at = NOW()
  WHERE category_slug IN ('kinh-nghiem', 'travel-tips', 'tips');
UPDATE posts SET category_name = 'Check-in', category_slug = 'check-in', updated_at = NOW()
  WHERE category_slug IN ('checkin', 'photo-spots', 'song-ao');

CREATE UNIQUE INDEX IF NOT EXISTS posts_source_url_unique ON posts (source_url) WHERE source_url IS NOT NULL AND source_url <> '';
CREATE INDEX IF NOT EXISTS posts_status_published_idx ON posts (status, published_at DESC);
CREATE INDEX IF NOT EXISTS posts_category_published_idx ON posts (category_slug, status, published_at DESC);
CREATE INDEX IF NOT EXISTS posts_country_published_idx ON posts (country_id, status, published_at DESC);
CREATE INDEX IF NOT EXISTS posts_destination_published_idx ON posts (destination_id, status, published_at DESC);
CREATE INDEX IF NOT EXISTS posts_featured_idx ON posts (featured, published_at DESC);
CREATE INDEX IF NOT EXISTS posts_created_idx ON posts (created_at DESC);
CREATE INDEX IF NOT EXISTS posts_search_idx ON posts USING GIN (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(excerpt, '') || ' ' || coalesce(category_name, '') || ' ' || coalesce(country_name, '') || ' ' || coalesce(destination_name, '')));

CREATE TABLE IF NOT EXISTS ingest_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL DEFAULT 'crawler-ai',
  received_count INTEGER NOT NULL DEFAULT 0,
  created_count INTEGER NOT NULL DEFAULT 0,
  updated_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'success',
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- Copyright reports and abuse-prevention counters.
CREATE TABLE IF NOT EXISTS copyright_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claimant_name TEXT NOT NULL,
  claimant_email TEXT NOT NULL,
  relationship TEXT NOT NULL CHECK (relationship IN ('owner', 'authorized_agent', 'other')),
  work_title TEXT NOT NULL DEFAULT '',
  original_work_url TEXT NOT NULL DEFAULT '',
  reported_url TEXT NOT NULL,
  details TEXT NOT NULL,
  declaration BOOLEAN NOT NULL DEFAULT FALSE,
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'reviewing', 'resolved', 'rejected')),
  review_note TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS copyright_reports_status_created_idx
  ON copyright_reports (status, created_at DESC);

CREATE TABLE IF NOT EXISTS copyright_report_rate_limits (
  ip_hash TEXT PRIMARY KEY,
  window_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  request_count INTEGER NOT NULL DEFAULT 0
);
