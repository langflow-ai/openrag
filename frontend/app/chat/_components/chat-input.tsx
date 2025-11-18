import { ArrowRight, Check, Funnel, Loader2, Plus } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import TextareaAutosize from "react-textarea-autosize";
import type { FilterColor } from "@/components/filter-icon-popover";
import { Button } from "@/components/ui/button";
import {
	Popover,
	PopoverAnchor,
	PopoverContent,
} from "@/components/ui/popover";
import { useFileDrag } from "@/hooks/use-file-drag";
import { cn } from "@/lib/utils";
import type { KnowledgeFilterData } from "../_types/types";
import { FilePreview } from "./file-preview";
import { SelectedKnowledgeFilter } from "./selected-knowledge-filter";

export interface ChatInputHandle {
	focusInput: () => void;
	clickFileInput: () => void;
}

interface ChatInputProps {
	input: string;
	loading: boolean;
	isUploading: boolean;
	selectedFilter: KnowledgeFilterData | null;
	isFilterDropdownOpen: boolean;
	availableFilters: KnowledgeFilterData[];
	filterSearchTerm: string;
	selectedFilterIndex: number;
	anchorPosition: { x: number; y: number } | null;
	parsedFilterData: { color?: FilterColor } | null;
	uploadedFile: File | null;
	onSubmit: (e: React.FormEvent) => void;
	onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
	onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
	onFilterSelect: (filter: KnowledgeFilterData | null) => void;
	onAtClick: () => void;
	onFilePickerClick: () => void;
	setSelectedFilter: (filter: KnowledgeFilterData | null) => void;
	setIsFilterHighlighted: (highlighted: boolean) => void;
	setIsFilterDropdownOpen: (open: boolean) => void;
	onFileSelected: (file: File | null) => void;
}

export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
	(
		{
			input,
			loading,
			isUploading,
			selectedFilter,
			isFilterDropdownOpen,
			availableFilters,
			filterSearchTerm,
			selectedFilterIndex,
			anchorPosition,
			parsedFilterData,
			uploadedFile,
			onSubmit,
			onChange,
			onKeyDown,
			onFilterSelect,
			onAtClick,
			onFilePickerClick,
			setSelectedFilter,
			setIsFilterHighlighted,
			setIsFilterDropdownOpen,
			onFileSelected,
		},
		ref,
	) => {
		const inputRef = useRef<HTMLTextAreaElement>(null);
		const fileInputRef = useRef<HTMLInputElement>(null);
		const [textareaHeight, setTextareaHeight] = useState(0);
		const [fileUploadError, setFileUploadError] = useState<Error | null>(null);
		const isDragging = useFileDrag();

		const { getRootProps, getInputProps } = useDropzone({
			accept: {
				"application/pdf": [".pdf"],
				"application/msword": [".doc"],
				"application/vnd.openxmlformats-officedocument.wordprocessingml.document":
					[".docx"],
				"text/markdown": [".md"],
			},
			maxFiles: 1,
			disabled: !isDragging,
			onDrop: (acceptedFiles, fileRejections) => {
				setFileUploadError(null);
				if (fileRejections.length > 0) {
					console.log(fileRejections);
					const message = fileRejections.at(0)?.errors.at(0)?.message;
					setFileUploadError(new Error(message));
					return;
				}
				onFileSelected(acceptedFiles[0]);
			},
		});

		useImperativeHandle(ref, () => ({
			focusInput: () => {
				inputRef.current?.focus();
			},
			clickFileInput: () => {
				fileInputRef.current?.click();
			},
		}));

		const handleFilePickerChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      setFileUploadError(null);
			const files = e.target.files;
			if (files && files.length > 0) {
				onFileSelected(files[0]);
			} else {
				onFileSelected(null);
			}
		};

		return (
			<div className="w-full">
				<form onSubmit={onSubmit} className="relative">
					{/* Outer container - flex-col to stack file preview above input */}
					<div
						{...getRootProps()}
						className={cn(
							"flex flex-col w-full p-2 rounded-xl border border-input transition-all",
							!isDragging &&
								"hover:[&:not(:focus-within)]:border-muted-foreground focus-within:border-foreground",
							isDragging && "border-dashed",
						)}
					>
						<input {...getInputProps()} />
						{/* File Preview Section - Always above */}
						<AnimatePresence>
							{uploadedFile && (
								<motion.div
									initial={{ opacity: 0, height: 0, marginBottom: 0 }}
									animate={{ opacity: 1, height: "auto", marginBottom: 8 }}
									exit={{ opacity: 0, height: 0, marginBottom: 0 }}
									className="overflow-hidden"
								>
									<FilePreview
										uploadedFile={uploadedFile}
										onClear={() => {
											onFileSelected(null);
										}}
									/>
								</motion.div>
							)}
						</AnimatePresence>
						<AnimatePresence>
							{fileUploadError && (
								<motion.p
									initial={{ opacity: 0, height: 0 }}
									animate={{ opacity: 1, height: "auto" }}
									exit={{ opacity: 0, height: 0 }}
									className="text-sm text-destructive overflow-hidden"
								>
									{fileUploadError.message}
								</motion.p>
							)}
						</AnimatePresence>
						<AnimatePresence>
							{isDragging && (
								<motion.div
									initial={{ opacity: 0, height: 0 }}
									animate={{ opacity: 1, height: 100 }}
									exit={{ opacity: 0, height: 0 }}
									className="overflow-hidden w-full flex flex-col items-center justify-center gap-2"
								>
									<p className="text-md font-medium text-primary">
										Add files to conversation
									</p>
									<p className="text-sm text-muted-foreground">
										Text formats and image files.{" "}
										<span className="font-semibold">10</span> files per chat,{" "}
										<span className="font-semibold">150 MB</span> each.
									</p>
								</motion.div>
							)}
						</AnimatePresence>
						{/* Main Input Container - flex-row or flex-col based on textarea height */}
						<div
							className={`relative flex w-full gap-2 ${
								textareaHeight > 40 ? "flex-col" : "flex-row items-center"
							}`}
						>
							{/* Filter + Textarea Section */}
							<div
								className={`flex items-center gap-2 ${textareaHeight > 40 ? "w-full" : "flex-1"}`}
							>
								{textareaHeight <= 40 &&
									(selectedFilter ? (
										<SelectedKnowledgeFilter
											selectedFilter={selectedFilter}
											parsedFilterData={parsedFilterData}
											onClear={() => {
												setSelectedFilter(null);
												setIsFilterHighlighted(false);
											}}
										/>
									) : (
										<Button
											type="button"
											variant="ghost"
											size="iconSm"
											className="h-8 w-8 p-0 rounded-md hover:bg-muted/50"
											onMouseDown={(e) => {
												e.preventDefault();
											}}
											onClick={onAtClick}
											data-filter-button
										>
											<Funnel className="h-4 w-4" />
										</Button>
									))}
								<div
									className="relative flex-1"
									style={{ height: `${textareaHeight}px` }}
								>
									<TextareaAutosize
										ref={inputRef}
										value={input}
										onChange={onChange}
										onKeyDown={onKeyDown}
										onHeightChange={(height) => setTextareaHeight(height)}
										maxRows={7}
										autoComplete="off"
										minRows={1}
										placeholder="Ask a question..."
										disabled={loading}
										className={`w-full text-sm bg-transparent focus-visible:outline-none resize-none`}
										rows={1}
									/>
								</div>
							</div>

							{/* Action Buttons Section */}
							<div
								className={`flex items-center gap-2 ${textareaHeight > 40 ? "justify-between w-full" : ""}`}
							>
								{textareaHeight > 40 &&
									(selectedFilter ? (
										<SelectedKnowledgeFilter
											selectedFilter={selectedFilter}
											parsedFilterData={parsedFilterData}
											onClear={() => {
												setSelectedFilter(null);
												setIsFilterHighlighted(false);
											}}
										/>
									) : (
										<Button
											type="button"
											variant="ghost"
											size="iconSm"
											className="h-8 w-8 p-0 rounded-md hover:bg-muted/50"
											onMouseDown={(e) => {
												e.preventDefault();
											}}
											onClick={onAtClick}
											data-filter-button
										>
											<Funnel className="h-4 w-4" />
										</Button>
									))}
								<div className="flex items-center gap-2">
									<Button
										type="button"
										variant="ghost"
										size="iconSm"
										onClick={onFilePickerClick}
										disabled={isUploading}
										className="h-8 w-8 p-0 !rounded-md hover:bg-muted/50"
									>
										<Plus className="h-4 w-4" />
									</Button>
									<Button
										variant="default"
										type="submit"
										size="iconSm"
										disabled={(!input.trim() && !uploadedFile) || loading}
										className="!rounded-md h-8 w-8 p-0"
									>
										{loading ? (
											<Loader2 className="h-4 w-4 animate-spin" />
										) : (
											<ArrowRight className="h-4 w-4" />
										)}
									</Button>
								</div>
							</div>
						</div>
					</div>
					<input
						ref={fileInputRef}
						type="file"
						onChange={handleFilePickerChange}
						className="hidden"
						accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
					/>

					<Popover
						open={isFilterDropdownOpen}
						onOpenChange={(open) => {
							setIsFilterDropdownOpen(open);
						}}
					>
						{anchorPosition && (
							<PopoverAnchor
								asChild
								style={{
									position: "fixed",
									left: anchorPosition.x,
									top: anchorPosition.y,
									width: 1,
									height: 1,
									pointerEvents: "none",
								}}
							>
								<div />
							</PopoverAnchor>
						)}
						<PopoverContent
							className="w-64 p-2"
							side="top"
							align="start"
							sideOffset={6}
							alignOffset={-18}
							onOpenAutoFocus={(e) => {
								// Prevent auto focus on the popover content
								e.preventDefault();
								// Keep focus on the input
							}}
						>
							<div className="space-y-1">
								{filterSearchTerm && (
									<div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
										Searching: @{filterSearchTerm}
									</div>
								)}
								{availableFilters.length === 0 ? (
									<div className="px-2 py-3 text-sm text-muted-foreground">
										No knowledge filters available
									</div>
								) : (
									<>
										{!filterSearchTerm && (
											<button
												type="button"
												onClick={() => onFilterSelect(null)}
												className={`w-full text-left px-2 py-2 text-sm rounded hover:bg-muted/50 flex items-center justify-between ${
													selectedFilterIndex === -1 ? "bg-muted/50" : ""
												}`}
											>
												<span>No knowledge filter</span>
												{!selectedFilter && (
													<Check className="h-4 w-4 shrink-0" />
												)}
											</button>
										)}
										{availableFilters
											.filter((filter) =>
												filter.name
													.toLowerCase()
													.includes(filterSearchTerm.toLowerCase()),
											)
											.map((filter, index) => (
												<button
													key={filter.id}
													type="button"
													onClick={() => onFilterSelect(filter)}
													className={`w-full overflow-hidden text-left px-2 py-2 gap-2 text-sm rounded hover:bg-muted/50 flex items-center justify-between ${
														index === selectedFilterIndex ? "bg-muted/50" : ""
													}`}
												>
													<div className="overflow-hidden">
														<div className="font-medium truncate">
															{filter.name}
														</div>
														{filter.description && (
															<div className="text-xs text-muted-foreground truncate">
																{filter.description}
															</div>
														)}
													</div>
													{selectedFilter?.id === filter.id && (
														<Check className="h-4 w-4 shrink-0" />
													)}
												</button>
											))}
										{availableFilters.filter((filter) =>
											filter.name
												.toLowerCase()
												.includes(filterSearchTerm.toLowerCase()),
										).length === 0 &&
											filterSearchTerm && (
												<div className="px-2 py-3 text-sm text-muted-foreground">
													No filters match &quot;{filterSearchTerm}&quot;
												</div>
											)}
									</>
								)}
							</div>
						</PopoverContent>
					</Popover>
				</form>
			</div>
		);
	},
);

ChatInput.displayName = "ChatInput";
