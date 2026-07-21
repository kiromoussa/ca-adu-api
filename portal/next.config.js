const path = require("path");

/**
 * ADU Atlas API developer portal - Next.js config.
 *
 * The portal lives at portal/ inside the ca-adu-api monorepo but reads its
 * jurisdiction and plan data straight from the repo-level config/*.yaml files
 * (single source of truth, no hardcoded coverage or pricing claims). Setting
 * outputFileTracingRoot to the repo root ensures Next's file tracer can find
 * ../config/*.yaml when Vercel's Root Directory is set to "portal".
 *
 * If deploying on Vercel with Root Directory = portal, also enable the
 * project setting "Include source files outside of the Root Directory in
 * the Build Step" so ../config and ../docs remain readable at build time.
 */
const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: path.join(__dirname, ".."),
};

module.exports = nextConfig;
