export function BrandMark({ size = 20 }: { size?: number }) {
  return (
    <svg className="brandmark" width={size} height={size * 0.82}
         viewBox="0 0 100 82" fill="none"
         role="img" aria-label="Verily">
      <rect x="4" y="9" width="92" height="64" rx="6" fill="var(--accent)" />
      {}
      <path d="M35 9 L35 46 L47 58 L90 15 L90 9 Z" fill="#ffffff" />
    </svg>
  );
}
