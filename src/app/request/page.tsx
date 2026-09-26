import { Suspense } from "react";
import { RequestComposer } from "@/components/rail/request-composer";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function NewRequestPage({
  searchParams,
}: {
  searchParams: Promise<{ scenario?: string }>;
}) {
  if (process.env.NODE_ENV !== "production" && process.env.DEMO_ENGINE_URL) redirect("/engine-demo#engine-request");
  const { scenario } = await searchParams;
  return (
    <Suspense>
      <RequestComposer preset={scenario ?? null} />
    </Suspense>
  );
}
