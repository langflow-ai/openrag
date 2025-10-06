import type { SVGProps } from "react";

export const AnimatedProcessingIcon = (props: SVGProps<SVGSVGElement>) => {
	return (
		<svg
			viewBox="0 0 8 12"
			fill="none"
			xmlns="http://www.w3.org/2000/svg"
			{...props}
		>
			<title>Processing</title>
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
            }
            30% { 
              opacity: 1; 
            }
          }
        `}
			</style>
			<circle className="dot-1" cx="2" cy="6" r="1" fill="currentColor" />
			<circle className="dot-2" cx="2" cy="10" r="1" fill="currentColor" />
			<circle className="dot-3" cx="6" cy="2" r="1" fill="currentColor" />
			<circle className="dot-4" cx="6" cy="6" r="1" fill="currentColor" />
			<circle className="dot-5" cx="6" cy="10" r="1" fill="currentColor" />
		</svg>
	);
};
