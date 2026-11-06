import { createContext, useContext } from "react";

/** Agent, chat, Ask AI and AI settings. The server's /api/config sends
 *  `features.ai`; it is off unless STUDIO_AI_FEATURES is on. */
export const AiFeaturesContext = createContext(false);
export const useAiFeatures = () => useContext(AiFeaturesContext);
/** A config without `features` (an older server) keeps AI features shown. */
export const aiFeaturesFrom = (cfg: { features?: { ai?: boolean } } | null | undefined) =>
  cfg?.features?.ai !== false;
