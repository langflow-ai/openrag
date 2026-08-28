// Components
import Logo from "@/components/ui/Logo";
import Link from "@/components/ui/Link";
import Text from "@/components/ui/Text";

// Constants
import { LINKS } from "./constants";

// Styles
import styles from "./styles.module.scss";

const Footer = () => {
  return (
    <footer className={styles.footer}>
      <Logo />
      <div className={styles.footer__content}>
        <Text size={300} tagName="p">
          © 2025 All rights reserved <span>·</span>{" "}
          <span>Manage Privacy Choices</span>
        </Text>
        <div className={styles.footer__links}>
          {LINKS.map((link) => (
            <div key={link.title}>
              <Link href={link.href}>{link.title}</Link>
            </div>
          ))}
        </div>
      </div>
    </footer>
  );
};

export default Footer;
