interface AnimatedProcessingIconProps {
  className?: string;
  size?: number;
}

export const AnimatedProcessingIcon = ({
  className = "",
  size = 10,
}: AnimatedProcessingIconProps) => {
  const width = Math.round((size * 6) / 10);
  const height = size;

  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 6 10"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <style>
        {`
          .dot-1 { animation: pulse-wave 1.5s infinite; animation-delay: 0s; }
          .dot-2 { animation: pulse-wave 1.5s infinite; animation-delay: 0.1s; }
          .dot-3 { animation: pulse-wave 1.5s infinite; animation-delay: 0.2s; }
          .dot-4 { animation: pulse-wave 1.5s infinite; animation-delay: 0.3s; }
          .dot-5 { animation: pulse-wave 1.5s infinite; animation-delay: 0.4s; }
          
          @keyframes pulse-wave {
            0%, 60%, 100% { 
              opacity: 0.25; 
              transform: scale(1);
            }
            30% { 
              opacity: 1; 
              transform: scale(1.2);
            }
          }
        `}
      </style>
      <circle className="dot-1" cx="1" cy="5" r="1" fill="currentColor" />
      <circle className="dot-2" cx="1" cy="9" r="1" fill="currentColor" />
      <circle className="dot-3" cx="5" cy="1" r="1" fill="currentColor" />
      <circle className="dot-4" cx="5" cy="5" r="1" fill="currentColor" />
      <circle className="dot-5" cx="5" cy="9" r="1" fill="currentColor" />
    </svg>
  );
};
