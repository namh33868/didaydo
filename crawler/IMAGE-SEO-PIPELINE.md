# Image SEO pipeline

## What the crawler does

1. **Rights first:** a cover is only considered after image-specific license metadata, creator, source page, and relevance checks. The automatic allow-list is limited to Public Domain, CC0, and CC BY. CC BY-SA, NC, and ND are rejected because the site's publication model does not currently apply a ShareAlike license to derivatives.
2. **Download and self-host:** the crawler downloads the selected image over HTTPS, verifies that it is a supported raster image, converts it locally, and sends the processed WebP to the authenticated Didaydo API. The API stores the file in the public Vercel Blob store. Published posts use the Blob URL, not the source website's hotlink.
3. **SEO metadata:** the filename is lowercase, unaccented, hyphen-separated, and based on the article subject. Vietnamese alt text is saved to the post's `cover_alt`; attribution and license links are saved to `cover_credit`.
4. **Compression:** cover assets target 100 KB and are resized up to 1200 px wide. The batch utility defaults to 800 px for normal in-article images. The optimizer reports when the target cannot be met without further quality loss.

The cover pipeline preserves the original source URL, creator, license, source page, and license URL in crawler metadata. It records the new Blob URL, dimensions, WebP format, and final byte size as well.

## Upload architecture and one-time setup

- GitHub Actions does **not** need `BLOB_READ_WRITE_TOKEN`.
- The crawler sends each optimized WebP to `POST /api/internal/images` using the existing `SITE_INGEST_API_KEY`.
- The Next.js route verifies that key, checks the WebP signature and file size, then uploads to `images/covers/` using `@vercel/blob`.
- On Vercel, the Blob SDK obtains the platform-managed OIDC credential automatically when the Blob store is connected with OIDC. No OIDC token is copied into GitHub or browser code.

Create a **Public** Blob store in Vercel because article images must be readable by website visitors. Connect the store to the Didaydo project. For an existing store, after deploying the current `@vercel/blob` SDK, open **Storage → the Blob store → Projects**, open the project's context menu, and choose **Upgrade to OIDC** if that action is available. New OIDC connections may already be enabled; the workflow's Blob API preflight verifies real access.

The only GitHub secrets required for this image upload path are the existing `SITE_URL` and `SITE_INGEST_API_KEY`. Keep the ingest key private and do not commit it to the repository.

## Batch tool for a local image folder

Run from the `crawler` folder:

```bash
python batch_optimize_images.py ./input-images ./optimized-images --max-width 800 --max-bytes 102400
```

The tool creates SEO-friendly WebP files and an `image-manifest.json` with output names, alt text, dimensions, and byte sizes. It does not overwrite source files and does not upload the output folder.

For cover images, use a wider output (the automatic crawler uses 1200 px):

```bash
python batch_optimize_images.py ./input-images ./optimized-covers --max-width 1200 --max-bytes 102400
```

## Watermark policy

The crawler does **not** remove third-party watermarks or logos. It rejects metadata that explicitly indicates a watermarked preview, and visible watermarks must be reviewed and replaced with a clean, rights-cleared original. A license does not automatically grant permission to remove ownership marks or imply that the site owns the image. The pipeline also does not add a DiDayDo watermark to third-party images; any branding overlay needs a separate rights and design decision.
