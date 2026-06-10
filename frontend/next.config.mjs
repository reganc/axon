/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Self-contained server bundle so the Docker image ships only what it runs,
  // not node_modules.
  output: "standalone",
};

export default nextConfig;
