export default function ErrorBox({ message }: { message: string }) {
  return (
    <div className="error" role="alert">
      <b>✕ </b>
      {message}
    </div>
  );
}
