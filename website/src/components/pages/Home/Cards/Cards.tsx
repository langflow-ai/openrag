// Components
import Display from "@/components/ui/Display";
import Text from "@/components/ui/Text";

// Constants
import { CARDS } from "./constants";

// Styles
import styles from "./styles.module.scss";

const Cards = () => {
  return (
    <section className={styles.section}>
      <div className="container-wide">
        <div className={styles.section__content}>
          <Display
            size={400}
            weight={600}
            tagName="h2"
            className={styles.section__content_text}
          >
            {
              "AI is only as good as the knowledge it runs on. OpenRAG makes that power accessible to every developer, with IBM's open-source credibility behind it."
            }
          </Display>
          <div className="row w-100">
            {CARDS.map((card) => (
              <div className={`col-lg-4 ${styles.cards__col}`} key={card.text}>
                <div className={styles.cards__card}>
                  <card.icon />
                  <Text size={300} weight={500} tagName="h3">
                    {card.text}
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

export default Cards;
