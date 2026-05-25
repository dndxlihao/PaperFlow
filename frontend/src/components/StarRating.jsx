import { useState } from 'react'
import './StarRating.css'

export default function StarRating({ value, onChange, size = 20 }) {
  const [hover, setHover] = useState(0)

  return (
    <span className="star-rating">
      {[1, 2, 3, 4, 5].map(star => (
        <span
          key={star}
          className={`star ${star <= (hover || value) ? 'star-filled' : 'star-empty'}`}
          onClick={() => onChange && onChange(star)}
          onMouseEnter={() => setHover(star)}
          onMouseLeave={() => setHover(0)}
          style={{ fontSize: size, cursor: onChange ? 'pointer' : 'default' }}
        >
          ★
        </span>
      ))}
    </span>
  )
}
