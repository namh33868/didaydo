type CoverAttributionProps = {
  credit: string;
};

export function CoverAttribution({ credit }: CoverAttributionProps) {
  const sourceMatch = credit.match(/Nguồn ảnh:\\s*(https:\/\/[^\\s·]+)/i);
  const licenseMatch = credit.match(/Giấy phép:\\s*(https:\/\/[^\\s·]+)/i);
  const description = credit
    .replace(/\\s*·\\s*Nguồn ảnh:\\s*https:\/\/[^\\s·]+/i, "")
    .replace(/\\s*·\\s*Giấy phép:\\s*https:\/\/[^\\s·]+/i, "")
    .trim();

  if (!sourceMatch && !licenseMatch) {
    return <figcaption>{credit}</figcaption>;
  }

  return (
    <figcaption>
      {description}
      {sourceMatch && (
        <>
          {" · "}
          <a href={sourceMatch[1]} target="_blank" rel="noopener noreferrer nofollow">
            Nguồn ảnh
          </a>
        </>
      )}
      {licenseMatch && (
        <>
          {" · "}
          <a href={licenseMatch[1]} target="_blank" rel="noopener noreferrer nofollow">
            Giấy phép
          </a>
        </>
      )}
    </figcaption>
  );
}
