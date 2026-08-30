import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the trace root: a stray lockfile in the home directory otherwise
  // makes Next infer the wrong workspace root on this machine.
  outputFileTracingRoot: path.join(__dirname),
  agentRules: false,
  typescript: { ignoreBuildErrors: false },
};

export default nextConfig;
