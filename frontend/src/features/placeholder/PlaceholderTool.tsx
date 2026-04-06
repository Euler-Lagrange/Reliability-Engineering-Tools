import styles from "./PlaceholderTool.module.css";

interface PlaceholderToolProps {
  title: string;
  description: string;
}

export function PlaceholderTool({ title, description }: PlaceholderToolProps) {
  return (
    <div className={styles.shell}>
      <section className={styles.card}>
        <p className="eyebrow">Suite shell</p>
        <h2 className={styles.title}>{title}</h2>
        <p className={styles.body}>{description}</p>
        <div className={styles.chips}>
          <span className="status-chip status-chip--pending">Placeholder</span>
          <span className="status-chip status-chip--info">Shell wired</span>
        </div>
      </section>
    </div>
  );
}
