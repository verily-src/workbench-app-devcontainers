/** Brand theme: accent colors via :root[data-brand] and the header partner mark. */
export type Brand = "verily" | "partner";
export const BRAND_EVENT = "studio-brand";

export function applyBrand(brand: Brand | undefined) {
  const value = brand === "partner" ? "partner" : "verily";
  document.documentElement.dataset.brand = value;
  window.dispatchEvent(new CustomEvent(BRAND_EVENT, { detail: value }));
}

/** Partner logo file (add the approved asset at web/public/brand/partner-logo.svg). */
export const PARTNER_LOGO = "brand/partner-logo.svg";   // relative to the app path
