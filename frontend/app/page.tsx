"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/protected-route";

function HomePage() {
  const router = useRouter();

  useEffect(() => {
    // Redirect to chat page - the new home page
    router.replace("/chat");
  }, [router]);

  return null;
}

export default function ProtectedHomePage() {
  return (
    <ProtectedRoute>
      <HomePage />
    </ProtectedRoute>
  );
}
