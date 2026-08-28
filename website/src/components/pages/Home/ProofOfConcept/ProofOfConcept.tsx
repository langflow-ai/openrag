"use client";

// Hooks
import useCheckMobile from "@/hooks/useCheckMobile";

// Components
import Text from "@/components/ui/Text";
import Display from "@/components/ui/Display";
import Button from "@/components/ui/Button";
import StaticImage from "@/components/ui/StaticImage";

// Constants
import { BUTTONS } from "../Hero/constants";

// Styles
import styles from "./styles.module.scss";
import Link from "next/link";

const ProofOfConcept = () => {
  const { isMobile, isChecking } = useCheckMobile(768);

  return (
    <section className={styles.section}>
      <div className="container-wide">
        <Display size={500} weight={700} tagName="h2">
          Your Fastest Path to Agentic Search
        </Display>
        <Text weight={500} size={500} tagName="p">
          A step-by-step visual pipeline that transforms your documents into an
          intelligent knowledge system.
        </Text>
        <div className={styles.section__buttons}>
          {BUTTONS.map((button) => (
            <Link href={button.link} key={button.title}>
              <Button key={button.title} type={button.type}>
                {button.title}
              </Button>
            </Link>
          ))}
        </div>
        {!isMobile && !isChecking && (
          <div className="position-relative">
            <StaticImage
              priority
              src="/assets/ProofOfConceptImage.webp"
              alt="command"
            />
            <code className={styles.section__code}>
              uv run openrag <span>█</span>
            </code>
          </div>
        )}
      </div>
      {isMobile && !isChecking && (
        <div className="position-relative">
          <StaticImage
            priority
            src="/assets/ProofOfConceptMobileImage.webp"
            alt="command"
          />
          <code className={styles.section__code}>
            uv run openrag <span>█</span>
          </code>
        </div>
      )}
    </section>
  );
};

export default ProofOfConcept;
