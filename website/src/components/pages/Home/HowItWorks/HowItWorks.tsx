// Components
import Display from "@/components/ui/Display";
import Text from "@/components/ui/Text";

// Constants
import { CARDS } from "./constants";

// Styles
import styles from "./styles.module.scss";

const HowItWorks = () => {
  return (
    <section className={styles.works}>
      <div className="container-wide">
        <Display size={500} weight={700} tagName="h2">
          How It Works
        </Display>
        <Text size={500} weight={500} tagName="p">
          A step-by-step visual pipeline that transforms your documents into an
          intelligent knowledge system.
        </Text>
        <div className={styles.works__cards}>
          <div className="row">
            {CARDS.map((card) => (
              <div
                className={`col-lg-6 col-xxl-3 ${styles.works__cards_col}`}
                key={card.title}
              >
                <div className={styles.works__cards_card}>
                  <card.icon />
                  <Display size={200} weight={700} tagName="h3">
                    {card.title}
                  </Display>
                  <Text size={300} tagName="p">
                    {card.subtitle}
                  </Text>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};

export default HowItWorks;
