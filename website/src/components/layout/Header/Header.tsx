"use client";

// Dependencies
import { useState } from "react";

// Compponents
import Logo from "@/components/ui/Logo";
// import Link from "@/components/ui/Link";
// import Button from "@/components/ui/Button";
import Close from "@/components/icons/Close";
// import Menu from "@/components/icons/Menu";

// Constants
// import { LINKS } from "./constants";

// Styles
import styles from "./styles.module.scss";

const Header = () => {
  const [isActive, setIsActive] = useState(false);

  const onToggle = () => {
    setIsActive(!isActive);
  };

  // const Links = () =>
  //   LINKS.map((link) => (
  //     <div key={link.title}>
  //       <Link href={link.href}>{link.title}</Link>
  //     </div>
  //   ));

  return (
    <header className={styles.header}>
      {isActive && (
        <div className={styles.header__drawer}>
          <div className="d-flex w-100 justify-content-between align-items-center">
            <Logo />
            <div onClick={onToggle}>
              <Close />
            </div>
          </div>
          <div className="d-flex flex-column justify-content-between h-100 w-100">
            <div className={styles.header__drawer_links}>{/* <Links /> */}</div>
            {/* <Button className={styles.drawer__button}>Get Started</Button> */}
          </div>
        </div>
      )}

      <Logo />
      <div className={styles.header__links}>
        {/* <Links /> */}
        {/* <Button>Get Started</Button> */}
      </div>
      <div className={styles.header__menu}>
        <div onClick={onToggle}>{/* <Menu /> */}</div>
      </div>
    </header>
  );
};

export default Header;
