// Components
import Text from "@/components/ui/Text";

// Constants
import { LOGOS } from "./constants";

// Styles
import styles from "./styles.module.scss";

const Community = () => (
  <section className={styles.community}>
    <div className="container-wide">
      <Text weight={500} size={500} tagName="h2">
        Backed by <span>1M+</span> OpenSearch downloads and an active dev
        community
      </Text>
      <div className={styles.community__logos}>
        {LOGOS.map((logo, index) => (
          <div key={index}>{logo.icon}</div>
        ))}
      </div>
    </div>
  </section>
);

export default Community;
