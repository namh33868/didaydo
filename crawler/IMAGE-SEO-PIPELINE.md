# Image SEO pipeline

## What the crawler does

1. **Rights first:** a cover is only considered after image-specific license metadata, creator, source page, and relevance checks. The automatic allow-list is limited to Public Domain, CC0, and CC BY. CC BY-SA, NC, and ND are rejected because the site's publication model does not currently apply a ShareAlike license to derivatives.
2. **Download and self-host:** the crawler downloads the selected image over HTTPS, verifies that it is a supported raster image, converts it locally, and uploads the processed WebP to a public Vercel Blob store. Published posts use the Blob URL, not the source website's hotlink.
3. **SEO metadata:** the filename is lowercase, unaccented, hyphen-separated, and based on the article subject. Vietnamese alt text is saved to the post's \`cover_alt\`; attribution and license links are saved to \`cover_credit\`.
4. **Compression:** cover assets target 100 KB and are resized up to 1200 px wide. The batch utility defaults to 800 px for normal in-article images. The optimizer reports when the target cannot be met without further quality loss.

The cover pipeline preserves the original source URL, creator, license, source page, and license URL in crawler metadata. It records the new Blob URL, dimensions, WebP format, and final byte size as well.

## One-time setup for automatic publishing

1. In the Vercel project, open **Storage → Create Database → Blob**.
2. Create a **Public** Blob store. Public access is required because article cover images must be readable by website visitors without authentication.
3. Copy the store's read/write token.
4. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret**.
5. Create a secret named \`BLOB_READ_WRITE_TOKEN\` and paste the token. Never commit the token or put it in a client-side environment variable.
6. The next workflow run checks the token before spending crawl/AI quota. The crawler uploads to \`images/covers/\` in Blob.

For a local run, set \`BLOB_READ_WRITE_TOKEN\` in the local environment or in the crawler's ignored \`.env\` file.

## Batch tool for a local image folder

Run from the \`crawler\` folder:

\`\`\`bash
python batch_optimize_images.py ./input-images ./optimized-images --max-width 800 --max-bytes 102400
\`\`\`

The tool creates SEO-friendly WebP files and an \`image-manifest.json\` with output names, alt text, dimensions, and byte sizes. It does not overwrite source files and does not upload the output folder.

For cover images, use a wider output (the automatic crawler uses 1200 px):

\`\`\`bash
python batch_optimize_images.py ./input-images ./optimized-covers --max-width 1200 --max-bytes 102400
\`\`\`

## Watermark policy

The crawler does **not** remove third-party watermarks or logos. It rejects metadata that explicitly indicates a watermarked preview, and visible watermarks must be reviewed and replaced with a clean, rights-cleared original. A license does not automatically grant permission to remove ownership marks or imply that the site owns the image. The pipeline also does not add a DiDayDo watermark to third-party images; any branding overlay needs a separate rights and design decision.
