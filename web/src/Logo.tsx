// The Kilta mark: a house with a wrench through it. Original artwork.
export function Logo({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="Kilta">
      <rect width="64" height="64" rx="16" className="fill-clay-600 dark:fill-clay-500" />
      <path d="M13 33 32 16l19 17v17H13z" fill="#fef3c7" />
      <path d="M28 50V38h8v12" fill="#c2671f" />
      <path
        d="M44 14a7 7 0 0 0-9 9L22 36l5 5 13-13a7 7 0 0 0 9-9l-4 4-4-1-1-4z"
        fill="#86411a"
      />
    </svg>
  );
}
