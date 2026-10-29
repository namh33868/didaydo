"""Mark a post as published after the website/CMS confirmed success.

This command does not publish to the website itself. It records the successful
publish result and then removes only that article's reusable output files.
"""
import argparse
import sys
import main as bot


def main():
    parser = argparse.ArgumentParser(description="Record successful publication and clean that article's output")
    parser.add_argument("--source-url", required=True, help="URL of the source article recorded by the crawler")
    parser.add_argument("--published-url", required=True, help="Canonical URL of the successfully published website post")
    parser.add_argument("--cms-post-id", help="Optional WordPress/CMS post ID")
    parser.add_argument("--confirm", action="store_true", help="Confirm the post is already published successfully")
    args = parser.parse_args()

    if not args.confirm:
        parser.error("Chưa xác nhận xuất bản. Chỉ thêm --confirm sau khi website/CMS báo thành công.")

    bot.init_db()
    result = bot.mark_published(args.source_url, args.published_url, args.cms_post_id)
    if result["cleanup_complete"]:
        print("Đã ghi lịch sử xuất bản và xóa output JSON/Markdown của bài.")
    else:
        print("Đã ghi lịch sử xuất bản, nhưng một số file chưa xóa được; bot sẽ thử dọn lại lần chạy sau.")
    print("Nguồn:", result["source_url"])
    print("Bài trên website:", result["publish_url"])


if __name__ == "__main__":
    main()
