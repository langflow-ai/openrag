// Dependencies
import { Metadata } from "next";

// Components
import Page from "@/components/layout/Page";
import Template from "@/components/pages/Home/Template";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.openr.ag";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "OpenRAG",
  description: "From Documents to Intelligent RAG in Minutes",
  openGraph: {
    url: siteUrl,
    siteName: "OpenRAG",
    title: "OpenRAG",
    description: "From Documents to Intelligent RAG in Minutes",
    images: [
      {
        url: "/assets/og-image.webp",
        width: 1200,
        height: 630,
        alt: "OpenRAG",
      },
    ],
  },
};

export default function Home() {
  return (
    <Page>
      <Template />
    </Page>
  );
}
