"use client";

// Hooks
import useCheckMobile from "@/hooks/useCheckMobile";

// Components
import Display from "@/components/ui/Display";
import StaticImage from "@/components/ui/StaticImage";
import Text from "@/components/ui/Text";
import Button from "@/components/ui/Button";

// Constants
import { BUTTONS } from "./constants";

// Styles
import styles from "./styles.module.scss";
import Link from "next/link";

const Hero = () => {
  const { isMobile, isChecking } = useCheckMobile(1050);

  return (
    <section className={styles.hero}>
      <div className="container">
        <Display
          tagName="h1"
          className={styles.hero__content_title}
          size={500}
          weight={700}
        >
          From Documents to Agentic Search in Minutes
        </Display>
        <Text size={400} className={styles.hero__content_text} tagName="p">
          {
            "IBM's open-source RAG distribution, powered by OpenSearch, Langflow, and Docling."
          }
        </Text>
        <div className={styles.hero__content_buttons}>
          {BUTTONS.map((button) => (
            <Link href={button.link} key={button.title}>
              <Button key={button.title} type={button.type}>
                {button.title}
              </Button>
            </Link>
          ))}
        </div>
      </div>
      {!isChecking && (
        <div className="position-relative">
          <StaticImage
            className={styles.hero__image}
            loading="eager"
            priority
            src={
              isMobile
                ? "/assets/HomeHeroMobileImage.webp"
                : "/assets/HomeHeroImage.webp"
            }
            alt="command"
          />
          <code>
            uv run openrag <span>█</span>
          </code>
        </div>
      )}
    </section>
  );
};

export default Hero;
