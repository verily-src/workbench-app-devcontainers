/** Brand theme: accent colors via :root[data-brand] and the header partner mark. */
export type Brand = "verily" | "23andme";
export const BRAND_EVENT = "studio-brand";

export function applyBrand(brand: Brand | undefined) {
  const value = brand === "23andme" ? "23andme" : "verily";
  document.documentElement.dataset.brand = value;
  window.dispatchEvent(new CustomEvent(BRAND_EVENT, { detail: value }));
}

/** Partner logo file (add the approved asset at web/public/brand/23andme-logo.svg). */
export const PARTNER_LOGO = "brand/23andme-logo.svg";   // relative to the app path
