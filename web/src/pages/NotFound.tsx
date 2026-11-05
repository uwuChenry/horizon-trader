import { Link } from "react-router-dom";
import { Empty } from "../components/ui";

export function NotFound() {
  return (
    <Empty>
      Nothing here.{" "}
      <Link to="/" className="text-accent hover:underline">
        Back to the overview
      </Link>
    </Empty>
  );
}
