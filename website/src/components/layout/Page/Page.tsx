// Dependencies
import { FC, PropsWithChildren } from "react";

// Components
import Header from "@/components/layout/Header";
import Footer from "@/components/layout/Footer";

type Props = PropsWithChildren;

const Page: FC<Props> = ({ children }) => {
  return (
    <>
      <Header />
      <main>{children}</main>
      <Footer />
    </>
  );
};

export default Page;
