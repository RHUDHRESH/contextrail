import { Suspense } from "react";
import { RequestComposer } from "@/components/rail/request-composer";

export const dynamic = "force-dynamic";

export default async function NewRequestPage({
  searchParams,
}: {
  searchParams: Promise<{ scenario?: string }>;
}) {
  const { scenario } = await searchParams;
  return (
    <Suspense>
      <RequestComposer preset={scenario ?? null} />
    </Suspense>
  );
}
