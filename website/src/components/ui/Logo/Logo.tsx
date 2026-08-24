// Dependencies
import Link from "next/link";

// Components
import LogoIcon from "@/components/icons/Logo";

// Styles
import styles from "./styles.module.scss";

const Logo = () => {
  return (
    <Link href="/" className={styles.logo}>
      <LogoIcon />
      OpenRAG
    </Link>
  );
};

export default Logo;
