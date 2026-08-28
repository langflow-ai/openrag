// Dependencies
import Script from "next/script";

// Styles
import "@/styles/index.scss";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <Script
          async
          src="https://www.googletagmanager.com/gtag/js?id=G-6Z1X4MSXCB"
        ></Script>
        <Script
          id="google-analytics"
          dangerouslySetInnerHTML={{
            __html: `
              window.dataLayer = window.dataLayer || [];
              function gtag(){dataLayer.push(arguments);}
              gtag('js', new Date());
              gtag('config', 'G-6Z1X4MSXCB');
            `,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
