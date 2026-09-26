import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the trace root: a stray lockfile in the home directory otherwise
  // makes Next infer the wrong workspace root on this machine.
  outputFileTracingRoot: path.join(__dirname),
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  agentRules: false,
  typescript: { ignoreBuildErrors: false },
};

export default nextConfig;
