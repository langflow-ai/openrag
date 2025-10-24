import { ArrowRight, Check, Funnel, Loader2, Plus, X } from "lucide-react";
import { forwardRef, useImperativeHandle, useRef } from "react";
import TextareaAutosize from "react-textarea-autosize";
import type { FilterColor } from "@/components/filter-icon-popover";
import { filterAccentClasses } from "@/components/knowledge-filter-panel";
import { Button } from "@/components/ui/button";
import {
	Popover,
	PopoverAnchor,
	PopoverContent,
} from "@/components/ui/popover";
import type { KnowledgeFilterData } from "../types";

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
	textareaHeight: number;
	parsedFilterData: { color?: FilterColor } | null;
	onSubmit: (e: React.FormEvent) => void;
	onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
	onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
	onHeightChange: (height: number) => void;
	onFilterSelect: (filter: KnowledgeFilterData | null) => void;
	onAtClick: () => void;
	onFilePickerChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
	onFilePickerClick: () => void;
	setSelectedFilter: (filter: KnowledgeFilterData | null) => void;
	setIsFilterHighlighted: (highlighted: boolean) => void;
	setIsFilterDropdownOpen: (open: boolean) => void;
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
			textareaHeight,
			parsedFilterData,
			onSubmit,
			onChange,
			onKeyDown,
			onHeightChange,
			onFilterSelect,
			onAtClick,
			onFilePickerChange,
			onFilePickerClick,
			setSelectedFilter,
			setIsFilterHighlighted,
			setIsFilterDropdownOpen,
		},
		ref,
	) => {
		const inputRef = useRef<HTMLTextAreaElement>(null);
		const fileInputRef = useRef<HTMLInputElement>(null);

		useImperativeHandle(ref, () => ({
			focusInput: () => {
				inputRef.current?.focus();
			},
			clickFileInput: () => {
				fileInputRef.current?.click();
			},
		}));

		return (
				<div className="w-full">
					<form onSubmit={onSubmit} className="relative">
						<div className="relative flex items-center w-full p-2 gap-2 rounded-xl border border-input focus-within:ring-1 focus-within:ring-ring">
							{selectedFilter ? (
								<span
									className={`inline-flex items-center p-1 rounded-sm text-xs font-medium transition-colors ${
										filterAccentClasses[parsedFilterData?.color || "zinc"]
									}`}
								>
									{selectedFilter.name}
									<button
										type="button"
										onClick={() => {
											setSelectedFilter(null);
											setIsFilterHighlighted(false);
										}}
										className="ml-0.5 rounded-full p-0.5"
									>
										<X className="h-4 w-4" />
									</button>
								</span>
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
							)}
							<div
								className="relative flex-1"
								style={{ height: `${textareaHeight}px` }}
							>
								<TextareaAutosize
									ref={inputRef}
									value={input}
									onChange={onChange}
									onKeyDown={onKeyDown}
									onHeightChange={onHeightChange}
									maxRows={7}
									minRows={1}
									placeholder="Ask a question..."
									disabled={loading}
									className={`w-full text-sm bg-transparent focus-visible:outline-none resize-none`}
									rows={1}
								/>
							</div>
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
								disabled={!input.trim() || loading}
								className="!rounded-md h-8 w-8 p-0"
							>
								{loading ? (
									<Loader2 className="h-4 w-4 animate-spin" />
								) : (
									<ArrowRight className="h-4 w-4" />
								)}
							</Button>
						</div>
						<input
							ref={fileInputRef}
							type="file"
							onChange={onFilePickerChange}
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
