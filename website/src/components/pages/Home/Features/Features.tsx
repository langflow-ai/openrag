// Components
import Text from "@/components/ui/Text";
import Display from "@/components/ui/Display";

// Constants
import { FEATURES } from "./constants";

// Styles
import styles from "./styles.module.scss";

const Features = () => {
  return (
    <section className={styles.features}>
      <div className="container-wide">
        <Display
          tagName="h2"
          className={styles.features__title}
          size={500}
          weight={700}
        >
          Core Features
        </Display>
        <div className="row">
          {FEATURES.map((feature) => (
            <div
              className={`col-12 col-md-6 col-lg-4 ${styles.features__col}`}
              key={feature.title}
            >
              <div className={styles.features__feature}>
                <div className={styles.features__feature_icon}>
                  <feature.icon />
                </div>
                <Text weight={500} size={300} tagName="h3">
                  {feature.title}
                </Text>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default Features;
