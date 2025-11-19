import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { useGetIBMModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import IBMLogo from "@/components/icons/ibm-logo";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import {
	WatsonxSettingsForm,
	type WatsonxSettingsFormData,
} from "./watsonx-settings-form";
import { useRouter } from "next/navigation";

const WatsonxSettingsDialog = ({
	open,
	setOpen,
}: {
	open: boolean;
	setOpen: (open: boolean) => void;
}) => {
	const queryClient = useQueryClient();
	const [isValidating, setIsValidating] = useState(false);
	const [validationError, setValidationError] = useState<Error | null>(null);
	const router = useRouter();

	const methods = useForm<WatsonxSettingsFormData>({
		mode: "onSubmit",
		defaultValues: {
			endpoint: "https://us-south.ml.cloud.ibm.com",
			apiKey: "",
			projectId: "",
		},
	});

	const { handleSubmit, watch } = methods;
	const endpoint = watch("endpoint");
	const apiKey = watch("apiKey");
	const projectId = watch("projectId");

	const { refetch: validateCredentials } = useGetIBMModelsQuery(
		{
			endpoint: endpoint,
			apiKey: apiKey,
			projectId: projectId,
		},
		{
			enabled: false,
		},
	);

	const settingsMutation = useUpdateSettingsMutation({
		onSuccess: () => {
			// Update provider health cache to healthy since backend validated the setup
			const healthData: ProviderHealthResponse = {
				status: "healthy",
				message: "Provider is configured and working correctly",
				provider: "watsonx",
			};
			queryClient.setQueryData(["provider", "health"], healthData);

			toast.message("IBM watsonx.ai successfully configured", {
				description:
					"You can now access the provided language and embedding models.",
				duration: Infinity,
				closeButton: true,
				icon: <IBMLogo className="w-4 h-4 text-[#1063FE]" />,
				action: {
					label: "Settings",
					onClick: () => {
						router.push("/settings?focusLlmModel=true");
					},
				},
			});
			setOpen(false);
		},
	});

	const onSubmit = async (data: WatsonxSettingsFormData) => {
		// Clear any previous validation errors
		setValidationError(null);

		// Validate credentials by fetching models
		setIsValidating(true);
		const result = await validateCredentials();
		setIsValidating(false);

		if (result.isError) {
			setValidationError(result.error);
			return;
		}

		const payload: {
			watsonx_endpoint: string;
			watsonx_api_key?: string;
			watsonx_project_id: string;
		} = {
			watsonx_endpoint: data.endpoint,
			watsonx_project_id: data.projectId,
		};

		// Only include api_key if a value was entered
		if (data.apiKey) {
			payload.watsonx_api_key = data.apiKey;
		}

		// Submit the update
		settingsMutation.mutate(payload);
	};

	return (
		<Dialog open={open} onOpenChange={setOpen}>
			<DialogContent autoFocus={false} className="max-w-2xl">
				<FormProvider {...methods}>
					<form onSubmit={handleSubmit(onSubmit)} className="grid gap-4">
						<DialogHeader className="mb-2">
							<DialogTitle className="flex items-center gap-3">
								<div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
									<IBMLogo className="text-black" />
								</div>
								IBM watsonx.ai Setup
							</DialogTitle>
						</DialogHeader>

						<WatsonxSettingsForm
							modelsError={validationError}
							isLoadingModels={isValidating}
						/>

						<AnimatePresence mode="wait">
							{settingsMutation.isError && (
								<motion.div
									key="error"
									initial={{ opacity: 0, y: 10 }}
									animate={{ opacity: 1, y: 0 }}
									exit={{ opacity: 0, y: -10 }}
								>
									<p className="rounded-lg border border-destructive p-4">
										{settingsMutation.error?.message}
									</p>
								</motion.div>
							)}
						</AnimatePresence>
						<DialogFooter className="mt-4">
							<Button
								variant="outline"
								type="button"
								onClick={() => setOpen(false)}
							>
								Cancel
							</Button>
							<Button
								type="submit"
								disabled={settingsMutation.isPending || isValidating}
							>
								{settingsMutation.isPending
									? "Saving..."
									: isValidating
										? "Validating..."
										: "Save"}
							</Button>
						</DialogFooter>
					</form>
				</FormProvider>
			</DialogContent>
		</Dialog>
	);
};

export default WatsonxSettingsDialog;
