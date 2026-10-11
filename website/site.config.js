// The settings you are most likely to tweak. Loaded by every page before assets/site.js.
// (The download link, version and release notes are NOT here: they live in assets/release.json,
//  which tools/sync_release.py fills from a real release so the site can't drift from it.)

window.SITE = {
  name: "RL Analyser",
  tagline: "Understand why you win, and why you lose.",
  description: "RL Analyser replays every Rocket League match in 2D, finds the moments that decided it, compares your stats with your rank, and a private AI coach on your own PC tells you what to practise next.",

  // Must match service.py (PRICE_TEXT) and the price you create in Stripe
  priceMonthly: "$15.99",
  priceText: "$15.99 / month",

  supportEmail: "support@YOURDOMAIN",     // shown in the footer and legal pages; use a real address before launch
  legalName: "[Your name or company]",    // who the Terms and Privacy pages are from
  country: "[Your country]",              // governing law on the Terms page

  // Links in the footer. Leave a value empty ("") to hide it.
  social: { discord: "", youtube: "", x: "", github: "https://github.com/mbarr26/RLanalyser" },

  // Switch parts of the home page on or off
  sections: { howItWorks: true, features: true, deepDive: true, privacy: true, pricing: true, faq: true },
};
