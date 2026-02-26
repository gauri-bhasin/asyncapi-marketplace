import { Link, Route, Routes } from "react-router-dom";
import HomePage from "./pages/HomePage";
import TopicPage from "./pages/TopicPage";

export default function App() {
  return (
    <div className="container">
      <header>
        <h1>AsyncAPI Marketplace</h1>
        <Link to="/">Catalog</Link>
      </header>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/topic/:topicName" element={<TopicPage />} />
      </Routes>
    </div>
  );
}
