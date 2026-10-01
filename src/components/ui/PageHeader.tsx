interface PageHeaderProps {
  title: string;
  description: string;
  eyebrow?: string;
}

export function PageHeader({
  title,
  description,
  eyebrow,
}: PageHeaderProps) {
  return (
    <header className="page-header">
      {eyebrow && <p className="page-header__eyebrow">{eyebrow}</p>}
      <h1 className="page-header__title">{title}</h1>
      <p className="page-header__description">{description}</p>
    </header>
  );
}