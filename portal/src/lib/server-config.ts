import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";

import type { JurisdictionsConfig, PlansConfig, SourcesConfig } from "./types";

// The portal is one workspace inside the ca-adu-api monorepo. It reads
// config/*.yaml from the repo root at build time (these pages are statically
// rendered) rather than duplicating jurisdiction or pricing data as
// hardcoded strings. We probe a short list of candidate roots so the loader
// works whether the build's cwd is portal/ (Vercel Root Directory = portal,
// the standard case) or the monorepo root.
const CANDIDATE_ROOTS = [
  path.join(process.cwd(), ".."),
  process.cwd(),
  path.join(process.cwd(), "..", ".."),
];

function readConfigFile(relativePath: string): string {
  const tried: string[] = [];
  for (const root of CANDIDATE_ROOTS) {
    const candidate = path.join(root, relativePath);
    tried.push(candidate);
    if (fs.existsSync(candidate)) {
      return fs.readFileSync(candidate, "utf8");
    }
  }
  throw new Error(
    `ADU Atlas portal: could not locate "${relativePath}". Checked: ${tried.join(", ")}. ` +
      "If deploying on Vercel with Root Directory=portal, enable " +
      '"Include source files outside of the Root Directory in the Build Step".'
  );
}

let jurisdictionsCache: JurisdictionsConfig | null = null;
let plansCache: PlansConfig | null = null;
let sourcesCache: SourcesConfig | null = null;

export function loadJurisdictionsConfig(): JurisdictionsConfig {
  if (!jurisdictionsCache) {
    const raw = readConfigFile(path.join("config", "jurisdictions.yaml"));
    jurisdictionsCache = yaml.load(raw) as JurisdictionsConfig;
  }
  return jurisdictionsCache;
}

export function loadPlansConfig(): PlansConfig {
  if (!plansCache) {
    const raw = readConfigFile(path.join("config", "plans.yaml"));
    plansCache = yaml.load(raw) as PlansConfig;
  }
  return plansCache;
}

export function loadSourcesConfig(): SourcesConfig {
  if (!sourcesCache) {
    const raw = readConfigFile(path.join("config", "sources.yaml"));
    sourcesCache = yaml.load(raw) as SourcesConfig;
  }
  return sourcesCache;
}

export function sourceRegistryByKey(): Map<string, SourcesConfig["sources"][number]> {
  const config = loadSourcesConfig();
  return new Map(config.sources.map((entry) => [entry.key, entry]));
}

// Fixed display order for plan cards regardless of YAML map key order.
export const PLAN_ORDER = ["BASIC", "PRO", "ULTRA", "MEGA"] as const;
