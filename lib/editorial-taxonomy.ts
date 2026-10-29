import { slugify } from "./format";

export type EditorialCategory = {
  name: string;
  slug: string;
  description: string;
  displayOrder: number;
  aliases: string[];
};

/** Canonical editorial topics. Country and city are geography, never article topics. */
export const EDITORIAL_CATEGORIES: EditorialCategory[] = [
  { name: "Cẩm nang", slug: "cam-nang", description: "Hướng dẫn dễ áp dụng để chuẩn bị và tận hưởng chuyến đi.", displayOrder: 1, aliases: ["guide", "guides", "travel guide", "travel guides", "huong dan du lich"] },
  { name: "Kinh nghiệm du lịch", slug: "kinh-nghiem-du-lich", description: "Kinh nghiệm thực tế, mẹo hữu ích và lưu ý trước chuyến đi.", displayOrder: 2, aliases: ["kinh nghiem", "travel tips", "tips", "travel experience", "experience"] },
  { name: "Điểm đến", slug: "diem-den", description: "Giới thiệu quốc gia, thành phố và những nơi đáng khám phá.", displayOrder: 3, aliases: ["diem den viet nam", "destinations", "destination", "places to visit", "the gioi", "world"] },
  { name: "Check-in", slug: "check-in", description: "Góc chụp đẹp, địa điểm nổi bật và trải nghiệm đáng lưu lại.", displayOrder: 4, aliases: ["checkin", "check in", "photo spots", "instagrammable places", "song ao"] },
  { name: "Ẩm thực", slug: "am-thuc", description: "Món ngon địa phương, hàng quán và văn hóa ẩm thực.", displayOrder: 5, aliases: ["food", "food guide", "food and drink", "street food", "local food", "cuisine", "mon ngon", "mon an"] },
  { name: "Hotel review", slug: "hotel-review", description: "Đánh giá khách sạn, resort, homestay và nơi lưu trú.", displayOrder: 6, aliases: ["hotel", "hotels", "hotel reviews", "review khach san", "khach san", "resort review", "homestay", "accommodation", "luu tru"] },
  { name: "Lịch trình", slug: "lich-trinh", description: "Lịch trình tham khảo theo số ngày, khu vực và ngân sách.", displayOrder: 7, aliases: ["itinerary", "itineraries", "travel itinerary", "journey plan"] },
  { name: "Di chuyển", slug: "di-chuyen", description: "Cách đi lại, phương tiện và mẹo di chuyển tại điểm đến.", displayOrder: 8, aliases: ["transport", "transportation", "getting around", "how to get there"] },
  { name: "Văn hóa & địa phương", slug: "van-hoa-dia-phuong", description: "Văn hóa, phong tục và những câu chuyện từ cộng đồng bản địa.", displayOrder: 9, aliases: ["culture", "local culture", "van hoa", "di san"] },
  { name: "Chi phí & ngân sách", slug: "chi-phi-du-lich", description: "Dự trù chi phí và lên ngân sách cho chuyến đi.", displayOrder: 10, aliases: ["budget", "travel budget", "cost", "travel cost", "chi phi"] },
  { name: "Tin du lịch", slug: "tin-du-lich", description: "Tin mới, thay đổi và thông tin đáng chú ý trong ngành du lịch.", displayOrder: 11, aliases: ["travel news", "news", "tourism news", "tin tuc du lich"] },
];

const bySlug = new Map<string, EditorialCategory>(EDITORIAL_CATEGORIES.map((category): [string, EditorialCategory] => [category.slug, category]));
const aliasToSlug = new Map<string, string>();
for (const category of EDITORIAL_CATEGORIES) {
  for (const alias of category.aliases) aliasToSlug.set(slugify(alias), category.slug);
  aliasToSlug.set(slugify(category.name), category.slug);
}

/** Map common crawler/AI labels onto a small, consistent set of public categories. */
export function normalizeEditorialCategory(value: string | null | undefined): EditorialCategory {
  const slug = slugify((value || "").trim());
  const direct = bySlug.get(slug);
  if (direct) return direct;
  const mappedSlug = aliasToSlug.get(slug);
  if (mappedSlug) return bySlug.get(mappedSlug)!;

  if (/(hotel|khach-san|resort|homestay|accommodation|luu-tru)/.test(slug)) return bySlug.get("hotel-review")!;
  if (/(am-thuc|food|cuisine|street-food|mon-ngon|mon-an|restaurant)/.test(slug)) return bySlug.get("am-thuc")!;
  if (/(check-in|checkin|photo-spot|song-ao)/.test(slug)) return bySlug.get("check-in")!;
  if (/(diem-den|destination|places-to-visit|the-gioi|world)/.test(slug)) return bySlug.get("diem-den")!;
  if (/(kinh-nghiem|travel-tip|experience|tips)/.test(slug)) return bySlug.get("kinh-nghiem-du-lich")!;
  if (/(lich-trinh|itinerary|plan)/.test(slug)) return bySlug.get("lich-trinh")!;
  if (/(di-chuyen|transport|getting-around)/.test(slug)) return bySlug.get("di-chuyen")!;
  if (/(van-hoa|culture|di-san|local)/.test(slug)) return bySlug.get("van-hoa-dia-phuong")!;
  if (/(chi-phi|budget|cost)/.test(slug)) return bySlug.get("chi-phi-du-lich")!;
  if (/(tin-tuc|news|tourism)/.test(slug)) return bySlug.get("tin-du-lich")!;
  return bySlug.get("cam-nang")!;
}
