import "dotenv/config";
import postgres from "postgres";
import { slugify } from "../lib/format";
import { EDITORIAL_CATEGORIES, normalizeEditorialCategory } from "../lib/editorial-taxonomy";

type DemoPost = {
  title: string;
  slug: string;
  excerpt: string;
  contentHtml: string;
  coverImage: string;
  coverAlt: string;
  category: string;
  tags: string[];
  featured: boolean;
  country?: string;
  destination?: string;
};

const demoPosts: DemoPost[] = [
  {
    title: "Đà Nẵng: thành phố biển để đi chậm và sống trọn từng khoảnh khắc",
    slug: "da-nang-thanh-pho-bien-di-cham",
    excerpt: "Từ bình minh bên biển Mỹ Khê đến những quán nhỏ trong lòng thành phố, Đà Nẵng luôn có cách riêng để khiến chuyến đi trở nên đáng nhớ.",
    contentHtml: `<p>Đà Nẵng là một điểm đến dễ yêu bởi nhịp sống vừa đủ năng động, vừa đủ thư thả. Bạn có thể bắt đầu ngày mới bằng một buổi đi bộ bên bờ biển, dành buổi trưa để khám phá những món ăn địa phương và kết thúc ngày bằng khoảnh khắc ngắm thành phố lên đèn.</p><h2>Bắt đầu ngày mới bên biển</h2><p>Biển Mỹ Khê thường đẹp nhất vào sáng sớm, khi nắng còn dịu và không khí trong lành. Hãy dành thời gian đi bộ, uống một ly cà phê và quan sát thành phố thức giấc thay vì cố gắng ghé thật nhiều điểm trong một buổi.</p><h2>Khám phá hương vị địa phương</h2><p>Mì Quảng, bún chả cá và bánh tráng cuốn thịt heo là những món đáng thử. Nên chọn quán đông khách địa phương, hỏi rõ giá trước khi gọi món và ưu tiên những nơi có thông tin vệ sinh minh bạch.</p><h2>Một lịch trình dễ chịu</h2><ul><li>Buổi sáng: đi bộ bên biển, ăn sáng địa phương.</li><li>Buổi chiều: ghé bảo tàng hoặc khám phá bán đảo Sơn Trà theo tuyến phù hợp.</li><li>Buổi tối: thưởng thức ẩm thực và dạo ven sông Hàn.</li></ul><p>Điều đáng nhớ nhất không phải là bao nhiêu điểm đã check-in, mà là bạn có đủ thời gian để cảm nhận nơi mình đến.</p>`,
    coverImage: "https://images.unsplash.com/photo-1559592413-7cec4d0cae2b?auto=format&fit=crop&w=1800&q=85",
    coverAlt: "Bờ biển miền Trung Việt Nam trong ánh nắng vàng",
    country: "Việt Nam",
    destination: "Đà Nẵng",
    category: "Điểm đến",
    tags: ["Đà Nẵng", "du lịch biển", "ẩm thực"],
    featured: true,
  },
  {
    title: "Hội An một ngày: lịch trình thong thả cho người thích phố cổ",
    slug: "hoi-an-mot-ngay-lich-trinh-thong-tha",
    excerpt: "Một ngày ở Hội An sẽ trọn vẹn hơn khi bạn biết dành khoảng trống cho những con hẻm nhỏ, quán cà phê và những khoảnh khắc không nằm trong lịch trình.",
    contentHtml: `<p>Hội An không cần một lịch trình dày đặc. Vẻ đẹp của phố cổ nằm ở những chi tiết nhỏ: bức tường vàng, giàn hoa giấy, chiếc đèn lồng và nhịp sống bên sông Hoài.</p><h2>Buổi sáng: đi bộ khi phố còn yên</h2><p>Hãy bắt đầu sớm để tránh nắng và có thời gian ngắm kiến trúc. Tôn trọng không gian sinh hoạt của người dân, không tự ý đi vào nhà riêng hoặc chụp ảnh khi chưa được đồng ý.</p><h2>Buổi trưa: thưởng thức món địa phương</h2><p>Cơm gà, cao lầu và các món mì là lựa chọn phổ biến. Bạn có thể hỏi người dân địa phương để tìm quán phù hợp với khẩu vị và ngân sách.</p><h2>Buổi chiều tối: bên dòng Hoài</h2><p>Khi trời dịu, hãy dành thời gian đi dạo ven sông. Nếu tham gia hoạt động trên thuyền, chọn đơn vị tuân thủ quy định an toàn và mặc áo phao đúng cách.</p>`,
    coverImage: "https://images.unsplash.com/photo-1533587851505-d119e13fa0d7?auto=format&fit=crop&w=1400&q=85",
    coverAlt: "Phố cổ Hội An với những ngôi nhà vàng đặc trưng",
    country: "Việt Nam",
    destination: "Hội An",
    category: "Điểm đến",
    tags: ["Hội An", "Quảng Nam", "lịch trình"],
    featured: false,
  },
  {
    title: "Đi du lịch bền vững: những thay đổi nhỏ tạo nên chuyến đi tốt hơn",
    slug: "du-lich-ben-vung-nhung-thay-doi-nho",
    excerpt: "Du lịch có trách nhiệm không nhất thiết phải phức tạp. Bắt đầu từ cách di chuyển, lựa chọn dịch vụ và tôn trọng văn hóa bản địa.",
    contentHtml: `<p>Một chuyến đi có trách nhiệm giúp bạn hiểu điểm đến sâu hơn, đồng thời giảm những tác động không cần thiết lên môi trường và cộng đồng địa phương.</p><h2>Ưu tiên dịch vụ tại địa phương</h2><p>Chọn hướng dẫn viên, nhà nghỉ, quán ăn và sản phẩm thủ công địa phương khi có điều kiện. Điều này giúp một phần chi tiêu quay trở lại cộng đồng nơi bạn ghé thăm.</p><h2>Giảm rác thải trong hành trình</h2><p>Mang bình nước có thể tái sử dụng, hạn chế đồ nhựa dùng một lần và luôn mang rác về nơi có điểm thu gom phù hợp.</p><h2>Tôn trọng văn hóa và thiên nhiên</h2><p>Tìm hiểu quy tắc ứng xử tại điểm đến, xin phép trước khi chụp ảnh người khác và không lấy động thực vật hay hiện vật tự nhiên làm quà.</p>`,
    coverImage: "https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?auto=format&fit=crop&w=1400&q=85",
    coverAlt: "Mặt hồ trong xanh và dãy núi nhìn từ một điểm du lịch thiên nhiên",
    category: "Cẩm nang",
    tags: ["du lịch bền vững", "môi trường", "kinh nghiệm"],
    featured: false,
  },
  {
    title: "Những điều nên chuẩn bị trước một chuyến đi tự túc",
    slug: "nhung-dieu-nen-chuan-bi-cho-chuyen-di-tu-tuc",
    excerpt: "Từ giấy tờ, chi phí đến phương án dự phòng, một checklist ngắn giúp chuyến đi tự túc nhẹ đầu hơn.",
    contentHtml: `<p>Du lịch tự túc cho bạn nhiều tự do, nhưng một chút chuẩn bị sẽ giúp hạn chế những tình huống bất ngờ.</p><h2>Kiểm tra giấy tờ và đặt chỗ</h2><p>Lưu bản sao giấy tờ quan trọng ở nơi an toàn, kiểm tra điều kiện đổi hoặc hủy vé và xác nhận giờ nhận phòng trước ngày khởi hành.</p><h2>Lập ngân sách thực tế</h2><p>Chia chi phí thành di chuyển, lưu trú, ăn uống, vé tham quan và khoản dự phòng. Không nên chỉ dựa vào giá được quảng cáo mà cần kiểm tra phụ phí.</p><h2>Chuẩn bị phương án dự phòng</h2><p>Lưu địa chỉ nơi ở, số điện thoại hỗ trợ và cách di chuyển thay thế. Khi đi vùng xa, hãy kiểm tra kết nối mạng và thông báo lịch trình cho người thân.</p>`,
    coverImage: "https://images.unsplash.com/photo-1473448912268-2022ce9509d8?auto=format&fit=crop&w=1400&q=85",
    coverAlt: "Con đường đi bộ giữa rừng xanh trong một chuyến du lịch",
    category: "Kinh nghiệm du lịch",
    tags: ["du lịch tự túc", "checklist", "chuẩn bị"],
    featured: false,
  },
  {
    title: "Ẩm thực đường phố: cách khám phá ngon miệng và an tâm hơn",
    slug: "am-thuc-duong-pho-kham-pha-an-tam",
    excerpt: "Ăn món địa phương là một phần thú vị của chuyến đi. Một vài nguyên tắc đơn giản giúp bạn lựa chọn hàng quán phù hợp.",
    contentHtml: `<p>Ẩm thực đường phố mở ra cách gần gũi để hiểu văn hóa của một nơi. Mỗi thành phố đều có những món ăn kể câu chuyện riêng về nguyên liệu, thói quen và lịch sử địa phương.</p><h2>Quan sát trước khi gọi món</h2><p>Ưu tiên nơi chế biến sạch sẽ, thực phẩm được bảo quản phù hợp và có lượng khách ổn định. Với món cần nấu chín, hãy dùng khi còn nóng.</p><h2>Hỏi giá và thành phần</h2><p>Hỏi trước giá, khẩu phần và thành phần nếu bạn có dị ứng thực phẩm. Đừng ngại nhờ người bán giải thích cách ăn món đó.</p><h2>Thưởng thức có trách nhiệm</h2><p>Chỉ gọi lượng bạn có thể ăn hết, mang theo chai nước cá nhân khi phù hợp và tránh để rác lại nơi công cộng.</p>`,
    coverImage: "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?auto=format&fit=crop&w=1400&q=85",
    coverAlt: "Các món ăn được bày trên bàn tại một quán ăn địa phương",
    category: "Ẩm thực",
    tags: ["ẩm thực", "món địa phương", "kinh nghiệm"],
    featured: false,
  },
  {
    title: "Sa Pa và lời mời gọi của những buổi sáng giữa mây",
    slug: "sa-pa-nhung-buoi-sang-giua-may",
    excerpt: "Một chuyến đi vùng cao không chỉ có cảnh đẹp; đó còn là dịp chậm lại, lắng nghe câu chuyện bản làng và chuẩn bị kỹ cho thời tiết thay đổi.",
    contentHtml: `<p>Sa Pa thường gợi nhớ đến núi non, ruộng bậc thang và những buổi sáng mây trôi qua thung lũng. Để chuyến đi thoải mái hơn, hãy dành khoảng trống cho thời tiết và ưu tiên trải nghiệm phù hợp với sức khỏe của cả nhóm.</p><h2>Chọn thời điểm và chuẩn bị trang phục</h2><p>Nhiệt độ vùng núi có thể thay đổi nhanh trong ngày. Mang theo áo khoác nhiều lớp, giày có độ bám tốt và kiểm tra dự báo thời tiết gần ngày khởi hành.</p><h2>Tôn trọng đời sống bản địa</h2><p>Khi ghé bản làng, hãy hỏi trước khi chụp ảnh người dân, mua hàng từ người làm ra sản phẩm khi có thể và tuân theo hướng dẫn tại các khu vực sinh hoạt cộng đồng.</p><h2>Đi vừa sức, ngắm lâu hơn</h2><p>Không cần gom quá nhiều điểm vào một ngày. Một cung đường ngắn, thời gian nghỉ hợp lý và một bữa ăn địa phương đôi khi tạo nên ký ức đáng giá nhất.</p>`,
    coverImage: "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1400&q=85",
    coverAlt: "Dãy núi xanh trong ánh sáng sớm",
    country: "Việt Nam",
    destination: "Sa Pa",
    category: "Điểm đến",
    tags: ["Sa Pa", "du lịch vùng cao", "thiên nhiên"],
    featured: false,
  },
  {
    title: "Bangkok qua những khu phố, khu chợ và bữa ăn giản dị",
    slug: "bangkok-kham-pha-khu-pho-va-am-thuc",
    excerpt: "Một vài gợi ý để khám phá Bangkok theo nhịp riêng: kết hợp phương tiện công cộng, tìm hiểu khu phố và dành thời gian thưởng thức ẩm thực địa phương.",
    contentHtml: `<p>Bangkok là thành phố có nhiều lớp trải nghiệm: những con phố sôi động, khu chợ, các không gian văn hóa và những quán ăn giản dị. Một lịch trình dễ chịu nên kết hợp vài điểm chính với thời gian tự do.</p><h2>Di chuyển theo khu vực</h2><p>Hãy gom các điểm đến gần nhau trong cùng một buổi để giảm thời gian đi lại. Với những hành trình đông người, phương tiện công cộng thường là lựa chọn dễ dự tính chi phí hơn.</p><h2>Khám phá ẩm thực có chọn lọc</h2><p>Quan sát điều kiện chế biến, hỏi giá trước khi gọi món và lưu ý thành phần nếu bạn có dị ứng. Mang theo tiền mặt mệnh giá nhỏ khi tới các khu chợ.</p><h2>Chuẩn bị trước khi đến</h2><p>Kiểm tra quy định nhập cảnh, giờ hoạt động của điểm tham quan và phương án di chuyển về nơi lưu trú vào buổi tối từ các nguồn chính thức trước chuyến đi.</p>`,
    coverImage: "https://images.unsplash.com/photo-1508009603885-50cf7c579365?auto=format&fit=crop&w=1400&q=85",
    coverAlt: "Khung cảnh đô thị Đông Nam Á với những tòa nhà và đường phố",
    country: "Thái Lan",
    destination: "Bangkok",
    category: "Điểm đến",
    tags: ["Bangkok", "Thái Lan", "ẩm thực đường phố"],
    featured: false,
  },
  {
    title: "Lên lịch trình thông minh: để chuyến đi có khoảng trống",
    slug: "len-lich-trinh-thong-minh-cho-chuyen-di",
    excerpt: "Một lịch trình tốt không cần kín từng giờ. Hãy dành thời gian cho việc di chuyển, nghỉ ngơi và những khám phá tình cờ.",
    contentHtml: `<p>Lịch trình là công cụ hỗ trợ chuyến đi, không phải danh sách cần hoàn thành bằng mọi giá. Khi xây dựng kế hoạch, hãy cân bằng giữa trải nghiệm muốn có và thời gian thực tế.</p><h2>Chọn một vài ưu tiên</h2><p>Ghi ra những điều quan trọng nhất với cả nhóm rồi sắp xếp theo vị trí địa lý. Những điểm còn lại có thể để làm lựa chọn dự phòng.</p><h2>Tính cả thời gian di chuyển</h2><p>Khoảng cách trên bản đồ không phản ánh đầy đủ tình hình giao thông, thời gian chờ hoặc việc tìm đường. Tránh xếp các hoạt động sát giờ nhau, nhất là khi cần đặt vé.</p><h2>Để trống một phần trong ngày</h2><p>Một khoảng nghỉ giúp chuyến đi bớt mệt và tạo cơ hội khám phá những địa điểm bạn tình cờ bắt gặp. Hãy kiểm tra lại giờ mở cửa và chính sách đặt chỗ sát ngày đi.</p>`,
    coverImage: "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=1400&q=85",
    coverAlt: "Con đường dài chạy qua phong cảnh rộng mở",
    category: "Kinh nghiệm du lịch",
    tags: ["lịch trình", "du lịch tự túc", "lập kế hoạch"],
    featured: false,
  },
];

async function main() {
  if (!process.env.DATABASE_URL) throw new Error("Missing DATABASE_URL. Copy .env.example to .env first.");
  const db = postgres(process.env.DATABASE_URL, { max: 1, prepare: false });
  try {
    for (const category of EDITORIAL_CATEGORIES) {
      await db`INSERT INTO categories (name, slug, description, display_order)
        VALUES (${category.name}, ${category.slug}, ${category.description}, ${category.displayOrder})
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, display_order = EXCLUDED.display_order`;
    }

    const starterCountries = [
      { name: "Việt Nam", order: 1, description: "Từ những thành phố sôi động đến biển đảo, núi rừng và di sản bản địa." },
      { name: "Nhật Bản", order: 2, description: "Khám phá văn hóa, ẩm thực, thành phố và những mùa du lịch tại Nhật Bản." },
      { name: "Thái Lan", order: 3, description: "Cẩm nang thành phố, bãi biển, ẩm thực đường phố và trải nghiệm ở Thái Lan." },
      { name: "Hàn Quốc", order: 4, description: "Kinh nghiệm, ẩm thực, mua sắm và các điểm đến tại Hàn Quốc." },
      { name: "Singapore", order: 5, description: "Gợi ý khám phá thành phố, ẩm thực và trải nghiệm tại Singapore." },
      { name: "Malaysia", order: 6, description: "Thành phố đa văn hóa, thiên nhiên và món ngon ở Malaysia." },
      { name: "Indonesia", order: 7, description: "Đảo, văn hóa, lưu trú và kinh nghiệm khám phá Indonesia." },
      { name: "Đài Loan", order: 8, description: "Chợ đêm, tuyến tàu, thiên nhiên và trải nghiệm tại Đài Loan." },
      { name: "Trung Quốc", order: 9, description: "Thành phố, di sản, ẩm thực và cẩm nang du lịch Trung Quốc." },
      { name: "Lào", order: 10, description: "Những hành trình chậm, văn hóa và thiên nhiên tại Lào." },
      { name: "Campuchia", order: 11, description: "Di sản, ẩm thực và những điểm đến nổi bật ở Campuchia." },
      { name: "Pháp", order: 12, description: "Thành phố, ẩm thực, nghệ thuật và kinh nghiệm du lịch Pháp." },
      { name: "Ý", order: 13, description: "Các thành phố lịch sử, ẩm thực và hành trình tại Ý." },
      { name: "Úc", order: 14, description: "Thiên nhiên, thành phố và cẩm nang khám phá nước Úc." },
      { name: "Hoa Kỳ", order: 15, description: "Gợi ý hành trình, thành phố và trải nghiệm tại Hoa Kỳ." },
    ];
    for (const country of starterCountries) {
      const countrySlug = slugify(country.name);
      await db`INSERT INTO destinations (name, slug, kind, parent_id, description, display_order, updated_at)
        VALUES (${country.name}, ${countrySlug}, 'country', NULL, ${country.description}, ${country.order}, NOW())
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, kind = 'country', parent_id = NULL,
          description = CASE WHEN destinations.description = '' THEN EXCLUDED.description ELSE destinations.description END,
          display_order = EXCLUDED.display_order, updated_at = NOW()`;
    }

    for (const post of demoPosts) {
      const normalizedCategory = normalizeEditorialCategory(post.category);
      const categoryName = normalizedCategory.name;
      const categorySlug = normalizedCategory.slug;
      let country: { id: string; name: string; slug: string } | null = null;
      let destination: { id: string; name: string; slug: string } | null = null;
      if (post.country) {
        const countrySlug = slugify(post.country);
        const countryRows = await db<{ id: string; name: string; slug: string }[]>`
          INSERT INTO destinations (name, slug, kind, parent_id, cover_image, updated_at)
          VALUES (${post.country}, ${countrySlug}, 'country', NULL, ${post.coverImage}, NOW())
          ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, cover_image = CASE WHEN destinations.cover_image = '' THEN EXCLUDED.cover_image ELSE destinations.cover_image END, updated_at = NOW()
          RETURNING id, name, slug
        `;
        country = countryRows[0] || null;
      }
      if (country && post.destination) {
        const destinationSlug = slugify(post.destination);
        const destinationRows = await db<{ id: string; name: string; slug: string }[]>`
          INSERT INTO destinations (name, slug, kind, parent_id, cover_image, updated_at)
          VALUES (${post.destination}, ${destinationSlug}, 'city', ${country.id}, ${post.coverImage}, NOW())
          ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, kind = 'city', parent_id = EXCLUDED.parent_id,
            cover_image = CASE WHEN destinations.cover_image = '' THEN EXCLUDED.cover_image ELSE destinations.cover_image END, updated_at = NOW()
          RETURNING id, name, slug
        `;
        destination = destinationRows[0] || null;
      }
      await db`
        INSERT INTO posts (title, slug, excerpt, content_html, cover_image, cover_alt, cover_credit,
          category_name, category_slug, country_id, country_name, country_slug, destination_id, destination_name, destination_slug,
          tags, status, featured, author_name, source_name, seo_title, seo_description, published_at)
        VALUES (${post.title}, ${post.slug}, ${post.excerpt}, ${post.contentHtml}, ${post.coverImage}, ${post.coverAlt}, '',
          ${categoryName}, ${categorySlug}, ${country?.id || null}, ${country?.name || ''}, ${country?.slug || ''},
          ${destination?.id || null}, ${destination?.name || ''}, ${destination?.slug || ''}, ${post.tags}, 'published', ${post.featured},
          'Ban biên tập', 'Đi Đây Đó', ${post.title}, ${post.excerpt}, NOW() - (floor(random() * 14)::text || ' days')::interval)
        ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title, excerpt = EXCLUDED.excerpt, content_html = EXCLUDED.content_html,
          cover_image = EXCLUDED.cover_image, cover_alt = EXCLUDED.cover_alt, category_name = EXCLUDED.category_name,
          category_slug = EXCLUDED.category_slug, country_id = EXCLUDED.country_id, country_name = EXCLUDED.country_name,
          country_slug = EXCLUDED.country_slug, destination_id = EXCLUDED.destination_id, destination_name = EXCLUDED.destination_name,
          destination_slug = EXCLUDED.destination_slug, tags = EXCLUDED.tags, status = 'published', featured = EXCLUDED.featured,
          seo_title = EXCLUDED.seo_title, seo_description = EXCLUDED.seo_description, updated_at = NOW()
      `;
    }
    await db`UPDATE posts SET category_name = 'Điểm đến', category_slug = 'diem-den', updated_at = NOW()
      WHERE category_slug IN ('the-gioi', 'diem-den-viet-nam', 'destinations', 'destination')`;
    await db`UPDATE posts SET category_name = 'Hotel review', category_slug = 'hotel-review', updated_at = NOW()
      WHERE category_slug IN ('hotel', 'hotels', 'hotel-reviews', 'review-khach-san', 'khach-san', 'homestay', 'resort-review')`;
    await db`UPDATE posts SET category_name = 'Ẩm thực', category_slug = 'am-thuc', updated_at = NOW()
      WHERE category_slug IN ('food', 'food-guide', 'street-food', 'food-and-drink', 'cuisine')`;
    await db`UPDATE posts SET category_name = 'Cẩm nang', category_slug = 'cam-nang', updated_at = NOW()
      WHERE category_slug IN ('guide', 'guides', 'travel-guide', 'travel-guides')`;
    await db`UPDATE posts SET category_name = 'Kinh nghiệm du lịch', category_slug = 'kinh-nghiem-du-lich', updated_at = NOW()
      WHERE category_slug IN ('kinh-nghiem', 'travel-tips', 'tips')`;
    await db`UPDATE posts SET category_name = 'Check-in', category_slug = 'check-in', updated_at = NOW()
      WHERE category_slug IN ('checkin', 'photo-spots', 'song-ao')`;

    console.log(`Seeded ${demoPosts.length} example travel posts and ${starterCountries.length} country records.`);
  } finally {
    await db.end();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
