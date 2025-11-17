"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/auth-context";
import { Lock, LogIn } from "lucide-react";

interface LoginRequiredProps {
  title?: string;
  description?: string;
  feature?: string;
}

export function LoginRequired({
  title = "Authentication Required",
  description = "You need to sign in to access this feature",
  feature,
}: LoginRequiredProps) {
  const { login } = useAuth();

  return (
    <div className="flex items-center justify-center min-h-[400px]">
      <Card className="max-w-md mx-auto">
        <CardHeader className="text-center">
          <div className="flex items-center justify-center w-12 h-12 bg-primary/10 rounded-full mx-auto mb-4">
            <Lock className="h-6 w-6 text-primary" />
          </div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>
            {feature ? `You need to sign in to access ${feature}` : description}
          </CardDescription>
        </CardHeader>
        <CardContent className="text-center">
          <Button onClick={login} className="w-full">
            <LogIn className="h-4 w-4 mr-2" />
            Sign In with Google
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
