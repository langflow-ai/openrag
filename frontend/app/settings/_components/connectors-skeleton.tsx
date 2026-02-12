import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function ConnectorsSkeleton() {
    return (
        <Card className="relative flex flex-col overflow-hidden">
            <CardHeader className="pb-3">
                <div className="flex flex-col items-start justify-between">
                    <div className="flex flex-col gap-4 w-full">
                        <div className="mb-1">
                            <Skeleton className="w-8 h-8 rounded border" />
                        </div>
                        <Skeleton className="h-4 w-1/3" />
                        <Skeleton className="h-4 w-1/2" />
                    </div>
                </div>
            </CardHeader>
            <CardContent className="flex-1 flex flex-col justify-end space-y-4 pt-px">
                <div className="flex gap-2">
                    <Skeleton className="h-8 w-24" />
                    <Skeleton className="h-8 w-8" />
                    <Skeleton className="h-8 w-8" />
                </div>
            </CardContent>
        </Card>
    );
}
